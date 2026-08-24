#!/usr/bin/env python3
import socket, struct, numpy as np, soundfile as sf, sys

audio_path = sys.argv[1]
audio, sr = sf.read(audio_path)
if audio.ndim > 1:
    audio = audio[:,0]
audio = audio.astype(np.float32)

c = socket.socket()
c.connect(('127.0.0.1', 10300))
c.sendall(struct.pack('>I', len(audio)) + audio.tobytes())
r = b''
while True:
    ch = c.recv(4096)
    if not ch: break
    r += ch
    if b'\n' in r: break
c.close()
print(r.decode().strip())
