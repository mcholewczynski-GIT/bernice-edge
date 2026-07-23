#!/usr/bin/env python3
"""
Bernice Routed Voice Loop
Wake word -> STT -> classify -> route to bernice-router OR grep KB + bernice-llm -> TTS
"""
import openwakeword, sounddevice as sd, numpy as np, scipy.signal as signal
import socket, struct, subprocess, time, logging, re

logging.basicConfig(level=logging.INFO, format='%(asctime)s [BERNICE] %(message)s')
log = logging.getLogger(__name__)

SR_IN = 48000
SR_WAKE = 16000
CHUNK_IN = 3840
CHUNK_WAKE = 1280
DEVICE = 'hw:1,0'
DEVICE_WAKE = 6
STT_HOST = '127.0.0.1'
STT_PORT = 10300
TTS_HOST = '127.0.0.1'
TTS_PORT = 10301
WAKE_THRESHOLD = 0.95
LISTEN_DURATION = 5
KB_PATH = '/mnt/xrt/knowledge'
MODEL_PATH = '/home/admin/nemo-env/lib/python3.12/site-packages/openwakeword/resources/models/hey_jarvis_v0.1.onnx'

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

BRIDGING_PHRASES = [
    'Let me check the XR Studio documentation for you.',
    'That needs a deeper look. Give me just a moment.',
    'I will pull that together for you now.',
]
_bridge_idx = 0

def is_xrt_query(text):
    t = text.lower()
    return any(trigger in t for trigger in XRT_TRIGGERS)

def grep_kb(query):
    keywords = ' '.join(re.findall(r'[a-z]{4,}', query.lower())[:5])
    pattern = '|'.join(re.findall(r'[a-z]{3,}', query.lower())[:6])
    if not pattern:
        pattern = 'service'
    # Always include XRT and studio as fallback terms
    if 'xrt' not in pattern and 'studio' not in pattern:
        pattern = pattern + '|xrt|studio'
    result = subprocess.run(
        ['grep', '-r', '-i', '-E', '-A', '8', '-B', '1', pattern,
         KB_PATH, '--include=*.md', '--exclude-dir=_placeholders'],
        capture_output=True, text=True
    )
    return result.stdout[:3000] if result.stdout else ''

def llm_fast(text):
    result = subprocess.run(
        ['hermes', '-z', text],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip()

def llm_deep(text, context):
    if context:
        prompt = f'Answer using only this XR Studio knowledge base context:\n\n{context}\n\nQuestion: {text}'
    else:
        prompt = text
    result = subprocess.run(
        ['hermes', '-z', prompt, '-m', 'bernice-llm:latest'],
        capture_output=True, text=True, timeout=90
    )
    return result.stdout.strip()

def stt(audio_48k):
    audio = audio_48k.astype(np.float32)
    c = socket.socket(); c.connect((STT_HOST, STT_PORT))
    c.sendall(struct.pack('>I', len(audio)) + audio.tobytes())
    r = b''
    while True:
        ch = c.recv(4096)
        if not ch: break
        r += ch
        if chr(10).encode() in r: break
    c.close()
    text = r.decode().strip()
    # Correct common XRT terminology misrecognitions
    corrections = {
        ' ex ': ' XRT ', ' ex.': ' XRT.', ' ex?': ' XRT?',
        'the ex ': 'the XRT ', 'x r t': 'XRT', 'x-r-t': 'XRT',
        'hick': 'HCIC', 'h c i c': 'HCIC',
    }
    for wrong, right in corrections.items():
        text = text.replace(wrong, right).replace(wrong.upper(), right)
    return text

def tts(text):
    c = socket.socket(); c.connect((TTS_HOST, TTS_PORT))
    data = text.encode('utf-8')
    c.sendall(struct.pack('>I', len(data)) + data)
    r = b''
    while True:
        ch = c.recv(1024)
        if not ch: break
        r += ch
        if chr(10).encode() in r: break
    c.close()

def handle_query(text):
    global _bridge_idx
    if is_xrt_query(text):
        log.info(f'XRT query detected - using KB + bernice-llm')
        bridge = BRIDGING_PHRASES[_bridge_idx % len(BRIDGING_PHRASES)]
        _bridge_idx += 1
        tts(bridge)
        context = grep_kb(text)
        log.info(f'KB context: {len(context)} chars retrieved')
        response = llm_deep(text, context)
    else:
        log.info(f'Conversational query - using bernice-router')
        response = llm_fast(text)
    log.info(f'Bernice: {response[:80]}...' if len(response) > 80 else f'Bernice: {response}')
    if response:
        tts(response)

def main():
    oww = openwakeword.Model(wakeword_model_paths=[MODEL_PATH])
    log.info('Bernice is listening... say Hey Jarvis to activate')
    audio_buffer = []
    state = 'wake'
    blocked_until = 0
    listen_end = 0
    listen_capture = None

    def callback(indata, frames, t, status):
        audio_buffer.extend(indata[:, 0].tolist())

    with sd.InputStream(samplerate=SR_WAKE, channels=1, dtype='float32',
                        device=DEVICE_WAKE, blocksize=CHUNK_WAKE, callback=callback):
        while True:
            now = time.time()
            if len(audio_buffer) < CHUNK_WAKE:
                time.sleep(0.005)
                continue
            chunk = np.array(audio_buffer[:CHUNK_WAKE])
            audio_buffer = audio_buffer[CHUNK_WAKE:]
            if state == 'blocked':
                if now >= blocked_until:
                    state = 'wake'
                    log.info('Ready - listening for wake word...')
            elif state == 'wake':
                pred = oww.predict((chunk * 32768).astype(np.int16))
                score = list(pred.values())[0]
                if score > WAKE_THRESHOLD:
                    log.info(f'Wake word detected (score={score:.2f})')
                    state = 'blocked'
                    audio_buffer.clear()
                    listen_capture = sd.rec(
                        int(LISTEN_DURATION * SR_IN),
                        samplerate=SR_IN, channels=1,
                        dtype='float32', device=DEVICE_WAKE
                    )
                    listen_end = now + LISTEN_DURATION
                    state = 'listen'
            elif state == 'listen':
                if now >= listen_end:
                    sd.wait()
                    state = 'blocked'
                    blocked_until = now + 8.0
                    audio_48k = listen_capture.flatten()
                    text = stt(audio_48k)
                    log.info(f'Heard: {text}')
                    if text:
                        handle_query(text)
                        word_count = len(text.split())
                        blocked_until = time.time() + max(5.0, word_count * 0.35)
                    log.info('Listening for wake word...')

if __name__ == '__main__': main()
