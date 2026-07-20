#!/usr/bin/env python3
"""
Bernice TTS Service
Accepts text on localhost:10301, synthesizes via Piper, plays via Tesira (plughw:1,0)
Protocol: 4-byte length header + UTF-8 text -> plays audio, returns 'OK' + newline
"""
import socket, struct, subprocess, logging, tempfile, os

logging.basicConfig(level=logging.INFO, format='%(asctime)s [TTS] %(message)s')
log = logging.getLogger(__name__)

HOST = '127.0.0.1'
PORT = 10301
MODEL = '/mnt/xrt/models/piper/en_GB-jenny_dioco-medium.onnx'
DEVICE = 'plughw:1,0'

def speak(text):
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        wav_path = f.name
    try:
        piper = subprocess.run(
            ['python3', '-m', 'piper', '--model', MODEL, '--output_file', wav_path],
            input=text.encode(),
            capture_output=True
        )
        if piper.returncode != 0:
            raise RuntimeError(piper.stderr.decode())
        subprocess.run(['aplay', '-D', DEVICE, wav_path], capture_output=True)
    finally:
        os.unlink(wav_path)

def handle(conn, addr):
    log.info(f'Connection from {addr}')
    try:
        h = conn.recv(4)
        if len(h) < 4: return
        n = struct.unpack('>I', h)[0]
        text = conn.recv(n).decode('utf-8')
        log.info(f'Speaking: {text[:60]}...' if len(text)>60 else f'Speaking: {text}')
        speak(text)
        conn.sendall(('OK' + chr(10)).encode())
    except Exception as e:
        log.error(f'Error: {e}')
        conn.sendall(('ERROR: ' + str(e) + chr(10)).encode())
    finally:
        conn.close()

def main():
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(5)
    log.info(f'TTS service listening on {HOST}:{PORT}')
    log.info(f'Voice: {MODEL}')
    log.info(f'Output: {DEVICE}')
    while True:
        conn, addr = s.accept()
        handle(conn, addr)

if __name__ == '__main__': main()
