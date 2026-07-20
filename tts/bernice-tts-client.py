#!/usr/bin/env python3
"""
Bernice TTS Client
Sends text to TTS service on localhost:10301
Usage: python3 bernice-tts-client.py 'text to speak'
       echo 'text' | python3 bernice-tts-client.py
"""
import sys, socket, struct

HOST = '127.0.0.1'
PORT = 10301

def speak(text):
    c = socket.socket()
    c.connect((HOST, PORT))
    data = text.encode('utf-8')
    c.sendall(struct.pack('>I', len(data)) + data)
    r = b''
    while True:
        ch = c.recv(1024)
        if not ch: break
        r += ch
        if chr(10).encode() in r: break
    c.close()
    return r.decode().strip()

if __name__ == '__main__':
    if len(sys.argv) > 1:
        text = ' '.join(sys.argv[1:])
    else:
        text = sys.stdin.read().strip()
    result = speak(text)
    if result != 'OK':
        print(f'Error: {result}', file=sys.stderr)
