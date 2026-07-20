#!/usr/bin/env python3
import socket, struct, numpy as np, scipy.signal as signal
import soundfile as sf, tempfile, os, logging
import nemo.collections.asr as nemo_asr
import nemo.collections.asr.data.audio_to_text_lhotse_prompt as lhotse_prompt
import nemo.collections.asr.models.hybrid_rnnt_ctc_bpe_models_prompt as prompt_model
import torch

logging.basicConfig(level=logging.INFO, format='%(asctime)s [STT] %(message)s')
log = logging.getLogger(__name__)

HOST = '127.0.0.1'
PORT = 10300
SR_IN = 48000
SR_OUT = 16000
MODEL = '/mnt/xrt/models/nemotron-3.5-asr-streaming/nemotron-3.5-asr-streaming-0.6b.nemo'

def patch():
    cls = lhotse_prompt.LhotseSpeechToTextBpeDatasetWithPrompt
    orig = cls._get_prompt_index
    def pg(self, key):
        return orig(self, 'en-US' if key is None else key)
    cls._get_prompt_index = pg
    orig_fwd = prompt_model.EncDecHybridRNNTCTCBPEModelWithPrompt.forward
    def pf(self, *a, **kw):
        orig_cat = torch.cat
        def sc(t, dim=-1, **k):
            if len(t)==2 and dim==-1 and t[0].shape[1]!=t[1].shape[1]:
                n=min(t[0].shape[1],t[1].shape[1]); t=[t[0][:,:n,:],t[1][:,:n,:]]
            return orig_cat(t, dim=dim, **k)
        torch.cat=sc
        try: r=orig_fwd(self,*a,**kw)
        finally: torch.cat=orig_cat
        return r
    prompt_model.EncDecHybridRNNTCTCBPEModelWithPrompt.forward = pf

def load_model():
    log.info('Loading NeMo ASR model...')
    m = nemo_asr.models.EncDecHybridRNNTCTCBPEModelWithPrompt.restore_from(MODEL, strict=False)
    m.eval()
    log.info('Model ready.')
    return m

def transcribe(model, audio):
    a16 = signal.resample_poly(audio, 1, 3)
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        sf.write(f.name, a16.astype(np.float32), SR_OUT)
        r = model.transcribe([f.name])
    os.unlink(f.name)
    import re
    text = r[0].text if hasattr(r[0], 'text') else str(r[0])
    return re.sub(r'<[^>]+>', '', text).strip()

def handle(conn, addr, model):
    log.info(f'Connection from {addr}')
    try:
        h = conn.recv(4)
        if len(h) < 4: return
        n = struct.unpack('>I', h)[0]
        buf = b''
        while len(buf) < n*4:
            c = conn.recv(65536)
            if not c: break
            buf += c
        audio = np.frombuffer(buf, dtype=np.float32)
        log.info(f'Received {len(audio)/SR_IN:.2f}s')
        text = transcribe(model, audio)
        log.info(f'Result: {text}')
        conn.sendall((text + chr(10)).encode())
    except Exception as e:
        log.error(f'Error: {e}')
        conn.sendall(('ERROR: ' + str(e) + chr(10)).encode())
    finally:
        conn.close()

def main():
    patch()
    model = load_model()
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(5)
    log.info(f'STT listening on {HOST}:{PORT}')
    while True:
        try:
            conn, addr = s.accept()
            handle(conn, addr, model)
        except Exception as e:
            log.error(f'Server loop error: {e}')

if __name__ == '__main__': main()
