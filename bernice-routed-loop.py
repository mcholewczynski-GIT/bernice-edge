#!/usr/bin/env python3
"""Bernice Routed Voice Loop with VAD - single stream architecture"""
import sys
sys.path.insert(0, '/home/admin')
from hdmi_intent import parse_hdmi_intent
from hdmi_switch import switch_input, get_all_routes, SwitcherError
# Bernice Edge skill (Crestron Collab Compute). Off unless BERNICE_EDGE_ENABLED=1;
# if the modules are missing the loop runs exactly as before.
try:
    from edge_intent import parse_edge_intent
    from edge_skill import handle_edge, ENABLED as EDGE_ENABLED
except ImportError:
    EDGE_ENABLED = False
import openwakeword, sounddevice as sd, numpy as np, scipy.signal as signal
import socket, struct, subprocess, time, logging, re, collections, json
from pathlib import Path

OVERLAY_STATE = Path('/home/admin/bernice-overlay/state.json')

def overlay(updates):
    try:
        state = json.loads(OVERLAY_STATE.read_text()) if OVERLAY_STATE.exists() else {}
        state.update(updates)
        state['updated'] = time.time()
        OVERLAY_STATE.write_text(json.dumps(state))
        # Also send via TCP to broadcast to WebSocket clients
        try:
            s = socket.socket()
            s.settimeout(0.5)
            s.connect(('127.0.0.1', 8767))
            s.sendall(f'json {json.dumps(updates)}'.encode())
            s.close()
        except: pass
    except: pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s [BERNICE] %(message)s')
log = logging.getLogger(__name__)

SR_WAKE = 16000
SR_STT = 48000
DEVICE = 6
CHUNK_WAKE = 1280
VAD_FRAME = 480
STT_HOST = '127.0.0.1'
STT_PORT = 10300
TTS_HOST = '127.0.0.1'
TTS_PORT = 10301
WAKE_THRESHOLD = 0.7
SILENCE_SECONDS = 3.0
MAX_LISTEN_SECONDS = 15.0
KB_PATH = '/mnt/xrt/knowledge'
MODEL_PATH = '/mnt/xrt/models/hey_bernice.onnx'
MAX_HISTORY_TURNS = 2
_pending_hdmi_input = None  # disambiguation state
conversation_history = []
_bridge_idx = 0

XRT_TRIGGERS = [
    'xr studio', 'xrt', 'hcic', 'bernice', 'visualization',
    'motion capture', 'spatial audio', 'immersive', 'preset',
    'technician', 'safe standby', 'vr mode', 'rendering',
    'generative', 'led wall', 'audio mode', 'service mode',
    'what can you', 'what do you', 'how do i', 'which mode',
    'set up the room', 'help me with', 'what is the room',
    'what is the xr', 'how does the', 'what services',
    'how do you', 'what are you designed', 'what can the',
]
BRIDGING = ['Let me check the XR Studio documentation for you.',
            'That needs a deeper look. Give me just a moment.',
            'I will pull that together for you now.']

def is_xrt(t): return any(x in t.lower() for x in XRT_TRIGGERS)

def grep_kb(query):
    pat = '|'.join(re.findall(r'[a-z]{3,}', query.lower())[:6]) or 'service'
    if 'xrt' not in pat and 'studio' not in pat: pat += '|xrt|studio'
    r = subprocess.run(['grep','-r','-i','-E','-A','8','-B','1',pat,
        KB_PATH,'--include=*.md','--exclude-dir=_placeholders'],
        capture_output=True, text=True)
    return r.stdout[:1500]  # tighter context for bernice-router's 4096 token window

def build_ctx():
    if not conversation_history: return ''
    ctx = '[Session context:]\n'
    for t in conversation_history[-(MAX_HISTORY_TURNS*2):]:
        ctx += f"{'Operator' if t['role']=='user' else 'Bernice'}: {t['content']}\n"
    return ctx + '\n'

import urllib.request as _urllib

def _ollama_chat(prompt, model='bernice-lightning:latest', think=False):
    payload = {
        'model': model,
        'think': think,
        'stream': False,
        'messages': [{'role': 'user', 'content': prompt}]
    }
    req = _urllib.Request(
        'http://localhost:11434/api/chat',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'}
    )
    with _urllib.urlopen(req, timeout=30) as resp:
        r = json.loads(resp.read())
    return r['message']['content'].strip()

def llm_fast(text):
    return _ollama_chat(build_ctx() + text)

def llm_deep(text, ctx):
    prompt = build_ctx() + (f'Answer using only this XR Studio KB:\n\n{ctx}\n\nQuestion: {text}' if ctx else text)
    return _ollama_chat(prompt, model='bernice-llm:latest', think=False)

def llm_kb_fast(text, ctx):
    prompt = build_ctx() + (f'Answer using only this XR Studio knowledge base context:\n\n{ctx}\n\nQuestion: {text}\n\nProvide a complete, concise answer in 2-3 sentences maximum.' if ctx else text)
    return _ollama_chat(prompt)

COMPLEX_TRIGGERS = ['walk me through', 'step by step', 'full process', 'everything about',
    'compare', 'difference between', 'explain in detail', 'how do all']

def is_complex(text):
    return any(t in text.lower() for t in COMPLEX_TRIGGERS)

def stt(audio_48k):
    c = socket.socket(); c.connect((STT_HOST, STT_PORT))
    a = audio_48k.astype(np.float32)
    c.sendall(struct.pack('>I', len(a)) + a.tobytes())
    r = b''
    while True:
        ch = c.recv(4096)
        if not ch: break
        r += ch
        if b'\n' in r: break
    c.close()
    text = r.decode().strip()
    for w,rr in {' ex ':' XRT ',' ex.':' XRT.',' ex?':' XRT?','x r t':'XRT','hick':'HCIC'}.items():
        text = text.replace(w, rr)
    return text

# Acronyms to expand for TTS pronunciation
TTS_ACRONYMS = {
    'HCIC': 'H.C.I.C.',
    'XRT': 'X.R.T.',
    'XR': 'X.R.',
    'VR': 'V.R.',
    'AR': 'A.R.',
    'OSU': 'O.S.U.',
    'UIT': 'U.I.T.',
    'AV': 'A.V.',
    'HDMI': 'H.D.M.I.',
    'STT': 'S.T.T.',
    'TTS': 'T.T.S.',
    'LLM': 'L.L.M.',
    'API': 'A.P.I.',
    'TCP': 'T.C.P.',
    'IP': 'I.P.',
    'LED': 'L.E.D.',
    'Bernice': 'Bernease',
    'BERNICE': 'Bernease',
}

def expand_acronyms(text):
    import re
    for acronym, expansion in TTS_ACRONYMS.items():
        text = re.sub(r'\b' + acronym + r'\b', expansion, text)
    return text

def strip_markdown(text):
    import re
    text = re.sub(r'\*+', '', text)           # remove asterisks
    text = re.sub(r'#+\s*', '', text)          # remove headers
    text = re.sub(r'`+', '', text)             # remove backticks
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # links -> text
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)  # underscores
    text = re.sub(r'\s+', ' ', text).strip()
    text = expand_acronyms(text)
    return text

def tts(text):
    text = strip_markdown(text)
    c = socket.socket(); c.connect((TTS_HOST, TTS_PORT))
    d = text.encode()
    c.sendall(struct.pack('>I', len(d)) + d)
    r = b''
    while True:
        ch = c.recv(1024)
        if not ch: break
        r += ch
        if b'\n' in r: break
    c.close()

def handle_hdmi(intent: dict) -> str:
    global _pending_hdmi_input
    if intent['output'] is None:
        _pending_hdmi_input = intent['input']
        return "Output 1 or output 2?|AWAIT_FOLLOWUP"
    return _execute_hdmi_switch(intent['input'], intent['output'])

def handle_hdmi_followup(text: str) -> str:
    global _pending_hdmi_input
    import re
    out_match = re.search(r'output\s*(one|two|1|2)\b', text.lower())
    if not out_match or _pending_hdmi_input is None:
        _pending_hdmi_input = None
        return "Sorry, I didn't catch which output — output 1 or output 2?"
    word_num = {'one': 1, 'two': 2}
    out_num = word_num.get(out_match.group(1).lower()) or int(out_match.group(1))
    input_num = _pending_hdmi_input
    _pending_hdmi_input = None
    return _execute_hdmi_switch(input_num, out_num)

def _execute_hdmi_switch(input_num: int, output_num: int) -> str:
    try:
        ok = switch_input(input_num, output_num)
    except SwitcherError:
        return "I couldn't reach the HDMI switcher — check the network link."
    if ok:
        return f"Done — input {input_num} is now on output {output_num}."
    return "The switcher didn't confirm that route — you may want to check it manually."

def handle(text):
    global _bridge_idx, _pending_hdmi_input
    # Check for HDMI disambiguation followup first
    if _pending_hdmi_input is not None:
        log.info(f'HDMI followup: {text}')
        resp = handle_hdmi_followup(text)
        log.info(f'Bernice: {resp}')
        tts(strip_markdown(resp))
        overlay({'response': resp, 'status': 'speaking', 'mode': 'response'})
        word_count = len(resp.split())
        time.sleep(max(1.0, word_count * 0.3))
        overlay({'status': 'listening', 'wake_detected': False, 'mode': 'ambient'})
        return
    # Check for HDMI routing intent
    hdmi_intent = parse_hdmi_intent(text)
    if hdmi_intent is not None:
        log.info(f'HDMI intent: {hdmi_intent}')
        resp = handle_hdmi(hdmi_intent)
        await_followup = resp.endswith('|AWAIT_FOLLOWUP')
        resp = resp.replace('|AWAIT_FOLLOWUP', '')
        log.info(f'Bernice: {resp}')
        tts(strip_markdown(resp))
        overlay({'response': resp, 'status': 'speaking', 'mode': 'response'})
        word_count = len(resp.split())
        time.sleep(max(1.0, word_count * 0.3))
        if await_followup:
            # Stay in listen mode for the output number followup
            overlay({'status': 'listening', 'mode': 'response'})
            log.info('Awaiting HDMI output followup...')
            return
        overlay({'status': 'listening', 'wake_detected': False, 'mode': 'ambient'})
        return
    # Bernice Edge: delegate image requests to the Collab Compute
    edge_intent = parse_edge_intent(text) if EDGE_ENABLED else None
    if edge_intent is not None:
        log.info(f'Edge intent: {edge_intent}')
        resp = handle_edge(edge_intent, overlay, log)
        log.info(f'Bernice: {resp}')
        tts(strip_markdown(resp))
        overlay({'response': resp, 'status': 'speaking', 'mode': 'response'})
        time.sleep(max(1.0, len(resp.split()) * 0.3))
        overlay({'status': 'listening', 'wake_detected': False, 'mode': 'ambient'})
        return
    if is_xrt(text):
        ctx = grep_kb(text)
        if is_complex(text):
            log.info('XRT query (complex) - KB + bernice-llm')
            tts(BRIDGING[_bridge_idx % len(BRIDGING)]); _bridge_idx += 1
            resp = llm_deep(text, ctx)
        else:
            log.info('XRT query (simple) - KB + bernice-lightning')
            resp = llm_kb_fast(text, ctx)
    else:
        log.info('Conversational - bernice-lightning')
        resp = llm_fast(text)
    log.info(f'Bernice: {resp[:80]}')
    if resp:
        overlay({'response': strip_markdown(resp), 'status': 'speaking', 'mode': 'response'})
        conversation_history.append({'role':'user','content':text})
        conversation_history.append({'role':'assistant','content':resp})
        if len(conversation_history) > MAX_HISTORY_TURNS*2:
            conversation_history[:] = conversation_history[-MAX_HISTORY_TURNS*2:]
        tts(resp)
        word_count = len(resp.split())
        time.sleep(max(1.0, word_count * 0.3))

def main():
    oww = openwakeword.Model(wakeword_model_paths=[MODEL_PATH])
    # Energy-based speech detection (VAD score too low with PipeWire)
    SPEECH_RMS_THRESHOLD = 0.003  # tune if needed
    log.info('Bernice ready - say Hey Bernice')
    overlay({'status': 'listening', 'mode': 'ambient', 'visible': True, 'heard': '', 'response': '', 'wake_detected': False})

    # Single shared audio buffer - 16kHz from PipeWire
    buf_16k = []
    state = 'wake'
    blocked_until = 0.0
    listen_buf_48k = []
    last_speech = 0.0
    speech_found = False
    listen_start = 0.0

    def cb(indata, frames, t, status):
        buf_16k.extend(indata[:,0].tolist())

    with sd.InputStream(samplerate=SR_WAKE, channels=1, dtype='float32',
                        device=DEVICE, blocksize=CHUNK_WAKE, callback=cb):
        while True:
            now = time.time()
            if len(buf_16k) < CHUNK_WAKE:
                time.sleep(0.005); continue
            chunk_16k = np.array(buf_16k[:CHUNK_WAKE])
            buf_16k = buf_16k[CHUNK_WAKE:]

            if state == 'blocked':
                if now >= blocked_until:
                    state = 'wake'
                    log.info('Ready - listening for wake word...')

            elif state == 'wake':
                score = list(oww.predict((chunk_16k*32768).astype(np.int16)).values())[0]
                if score > WAKE_THRESHOLD:
                    log.info(f'Wake word (score={score:.2f}) - speak now')
                    overlay({'status':'listening','wake_detected':True,'heard':''})
                    state = 'listen'
                    blocked_until = now + 30.0
                    listen_buf_48k = []
                    last_speech = now
                    speech_found = False
                    listen_start = now
                    buf_16k.clear()

            elif state == 'listen':
                # Upsample 16k chunk to 48k for STT buffer
                chunk_48k = signal.resample_poly(chunk_16k, 3, 1).astype(np.float32)
                listen_buf_48k.extend(chunk_48k.tolist())
                # Energy-based speech detection
                rms = np.sqrt(np.mean(chunk_16k**2))
                is_speech = rms > SPEECH_RMS_THRESHOLD
                if is_speech:
                    if not speech_found: log.info('Speech detected'); overlay({'status':'processing'})
                    speech_found = True
                    last_speech = now
                silence = now - last_speech
                elapsed = now - listen_start
                if speech_found and silence >= SILENCE_SECONDS:
                    log.info(f'Silence {silence:.1f}s - processing')
                    state = 'blocked'
                    audio = np.array(listen_buf_48k, dtype=np.float32)
                    text = stt(audio)
                    log.info(f'Heard: {text}')
                    if text:
                        overlay({'heard': text, 'status': 'processing', 'mode': 'response'})
                        handle(text)
                    blocked_until = time.time() + 5.0
                    overlay({'status':'listening','wake_detected':False,'mode':'ambient'})
                    log.info('Listening for wake word...')
                elif elapsed > MAX_LISTEN_SECONDS:
                    log.info('Max listen time - processing')
                    state = 'blocked'
                    if listen_buf_48k:
                        audio = np.array(listen_buf_48k, dtype=np.float32)
                        text = stt(audio)
                        log.info(f'Heard: {text}')
                        if text: handle(text)
                    blocked_until = time.time() + 5.0
                    overlay({'status':'listening','wake_detected':False,'mode':'ambient'})
                    log.info('Listening for wake word...')
                elif not speech_found and elapsed > 8.0:
                    log.info('No speech - returning to wake')
                    state = 'blocked'
                    blocked_until = now + 3.0

if __name__ == '__main__':
    import traceback
    while True:
        try:
            main()
        except KeyboardInterrupt:
            log.info('Bernice shutting down')
            break
        except Exception as e:
            log.error(f'Main loop crashed: {e}')
            log.error(traceback.format_exc())
            log.info('Restarting in 5 seconds...')
            time.sleep(5)
