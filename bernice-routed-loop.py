#!/usr/bin/env python3
"""Bernice Routed Voice Loop with VAD - single stream architecture"""
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

def llm_fast(text):
    r = subprocess.run(['hermes','-z',build_ctx()+text], capture_output=True, text=True, timeout=30)
    return r.stdout.strip()

def llm_deep(text, ctx):
    prompt = build_ctx() + (f'Answer using only this XR Studio KB:\n\n{ctx}\n\nQuestion: {text}' if ctx else text)
    r = subprocess.run(['hermes','-z',prompt,'-m','bernice-llm:latest'], capture_output=True, text=True, timeout=90)
    return r.stdout.strip()

def llm_kb_fast(text, ctx):
    prompt = build_ctx() + (f'Answer using only this XR Studio knowledge base context:\n\n{ctx}\n\nQuestion: {text}\n\nProvide a complete, concise answer in 2-3 sentences maximum.' if ctx else text)
    r = subprocess.run(['hermes','-z',prompt], capture_output=True, text=True, timeout=30)
    return r.stdout.strip()

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

def strip_markdown(text):
    import re
    text = re.sub(r'\*+', '', text)           # remove asterisks
    text = re.sub(r'#+\s*', '', text)          # remove headers
    text = re.sub(r'`+', '', text)             # remove backticks
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # links -> text
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)  # underscores
    text = re.sub(r'\s+', ' ', text).strip()
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

def handle(text):
    global _bridge_idx
    if is_xrt(text):
        ctx = grep_kb(text)
        if is_complex(text):
            log.info('XRT query (complex) - KB + bernice-llm')
            tts(BRIDGING[_bridge_idx % len(BRIDGING)]); _bridge_idx += 1
            resp = llm_deep(text, ctx)
        else:
            log.info('XRT query (simple) - KB + bernice-router')
            resp = llm_kb_fast(text, ctx)
    else:
        log.info('Conversational - bernice-router')
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

if __name__ == '__main__': main()
