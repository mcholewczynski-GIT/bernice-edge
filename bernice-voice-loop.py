#!/usr/bin/env python3
"""
Bernice Voice Loop Test
STT -> Hermes -> TTS end-to-end
Usage: python3 bernice-voice-loop.py [duration_seconds]
"""
import sys, socket, struct, subprocess, numpy as np, sounddevice as sd

STT_HOST = '127.0.0.1'
STT_PORT = 10300
TTS_HOST = '127.0.0.1'
TTS_PORT = 10301
SR = 48000
DEV = 'hw:1,0'

def stt(duration=4):
    print(f'Listening for {duration}s...')
    audio = sd.rec(int(duration*SR), samplerate=SR, channels=1, dtype='float32', device=DEV)
    sd.wait()
    audio = audio.flatten()
    c = socket.socket(); c.connect((STT_HOST, STT_PORT))
    c.sendall(struct.pack('>I', len(audio)) + audio.astype(np.float32).tobytes())
    r = b''
    while True:
        ch = c.recv(4096)
        if not ch: break
        r += ch
        if chr(10).encode() in r: break
    c.close()
    return r.decode().strip()

def llm(text):
    result = subprocess.run(
        ['hermes', '-z', text],
        capture_output=True, text=True, timeout=60
    )
    return result.stdout.strip()

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

if __name__ == '__main__':
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    text = stt(duration)
    print(f'You said: {text}')
    if not text:
        print('No speech detected'); sys.exit()
    print('Thinking...')
    response = llm(text)
    print(f'Bernice: {response}')
    tts(response)
