#!/usr/bin/env python3
import openwakeword, sounddevice as sd, numpy as np, scipy.signal as signal
import socket, struct, subprocess, time, logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [WAKE] %(message)s')
log = logging.getLogger(__name__)

SR_IN = 48000
SR_WAKE = 16000
DEVICE_WAKE = 6
CHUNK_IN = 3840
CHUNK_WAKE = 1280
DEVICE = 'hw:1,0'
STT_HOST = '127.0.0.1'
STT_PORT = 10300
TTS_HOST = '127.0.0.1'
TTS_PORT = 10301
WAKE_THRESHOLD = 0.7
LISTEN_DURATION = 5
MODEL_PATH = '/home/admin/nemo-env/lib/python3.12/site-packages/openwakeword/resources/models/hey_jarvis_v0.1.onnx'

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
    return r.decode().strip()

def llm(text):
    result = subprocess.run(['hermes', '-z', text], capture_output=True, text=True, timeout=60)
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

def main():
    oww = openwakeword.Model(wakeword_model_paths=[MODEL_PATH])
    log.info('Bernice is listening... say Hey Jarvis to activate')
    audio_buffer = []
    state = 'wake'
    blocked_until = 0
    listen_end = 0
    listen_buffer = []

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
                    log.info('Listening for wake word...')
            elif state == 'wake':
                pred = oww.predict((chunk * 32768).astype(np.int16))
                score = list(pred.values())[0]
                if score > WAKE_THRESHOLD:
                    log.info(f'Wake word detected (score={score:.2f})')
                    state = 'blocked'
                    audio_buffer.clear()
                    log.info('Acknowledged - listening')
                    time.sleep(0.3)
                    audio_buffer.clear()
                    log.info(f'Listening for {LISTEN_DURATION}s...')
                    listen_capture = sd.rec(int(LISTEN_DURATION * SR_IN), samplerate=SR_IN, channels=1, dtype='float32', device=DEVICE_WAKE)
                    listen_end = time.time() + LISTEN_DURATION
                    listen_buffer = []
                    state = 'listen'
            elif state == 'listen':
                if now >= listen_end:
                    sd.wait()
                    state = 'blocked'
                    blocked_until = now + 8.0
                    audio_48k = listen_capture.flatten()
                    import soundfile as sf; sf.write('/tmp/wake_capture.wav', audio_48k, SR_IN)
                    log.info(f'Processing... buffer has {len(listen_buffer)} samples ({len(listen_buffer)/SR_IN:.1f}s)')
                    text = stt(audio_48k)
                    log.info(f'Heard: {text}')
                    if text:
                        response = llm(text)
                        log.info(f'Bernice: {response}')
                        word_count = len(response.split())
                        estimated_duration = max(8.0, word_count * 0.4 + 3.0)
                        tts(response)
                        time.sleep(estimated_duration)
                    else:
                        log.info('No speech detected')
                    blocked_until = time.time() + 5.0

if __name__ == '__main__': main()
