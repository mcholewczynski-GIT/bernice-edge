#!/usr/bin/env python3
import sys, socket, struct, numpy as np, sounddevice as sd

HOST = '127.0.0.1'
PORT = 10300
SR = 48000
DEV = 'hw:1,0'

def record(dur=3):
    print(f'Recording {dur}s...')
    a = sd.rec(int(dur*SR), samplerate=SR, channels=1, dtype='float32', device=DEV)
    sd.wait()
    return a.flatten()

def transcribe(audio):
    c = socket.socket()
    c.connect((HOST, PORT))
    c.sendall(struct.pack('>I', len(audio)) + audio.astype(np.float32).tobytes())
    r = b''
    while True:
        ch = c.recv(4096)
        if not ch: break
        r += ch
        if chr(10).encode() in r: break
    c.close()
    return r.decode().strip()

if __name__ == '__main__':
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    audio = record(dur)
    print('Sending to STT service...')
    print(transcribe(audio))
