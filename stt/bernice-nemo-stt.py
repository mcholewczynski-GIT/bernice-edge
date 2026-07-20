#!/usr/bin/env python3
"""
Bernice NeMo STT Pipeline
Captures from Tesira (hw:1,0), resamples 48kHz->16kHz, transcribes via NeMo ASR
Usage: python3 bernice-nemo-stt.py [duration_seconds]
"""
import sys
import numpy as np
import soundfile as sf
import scipy.signal as signal
import sounddevice as sd
import nemo.collections.asr as nemo_asr
import nemo.collections.asr.data.audio_to_text_lhotse_prompt as lhotse_prompt
import nemo.collections.asr.models.hybrid_rnnt_ctc_bpe_models_prompt as prompt_model
import torch
import tempfile, os

DEVICE = 'hw:1,0'
SAMPLE_RATE_IN = 48000
SAMPLE_RATE_OUT = 16000
CHANNELS = 1
MODEL_PATH = '/mnt/xrt/models/nemotron-3.5-asr-streaming/nemotron-3.5-asr-streaming-0.6b.nemo'

def apply_patches():
    # Patch 1: default language to en-US when None
    cls = lhotse_prompt.LhotseSpeechToTextBpeDatasetWithPrompt
    original_get = cls._get_prompt_index
    def patched_get(self, key):
        if key is None:
            key = 'en-US'
        return original_get(self, key)
    cls._get_prompt_index = patched_get

    # Patch 2: align prompt/encoded tensor sizes in forward pass
    original_forward = prompt_model.EncDecHybridRNNTCTCBPEModelWithPrompt.forward
    def patched_forward(self, *args, **kwargs):
        original_cat = torch.cat
        def safe_cat(tensors, dim=-1, **kw):
            if len(tensors) == 2 and dim == -1:
                t0, t1 = tensors
                if t0.shape[1] != t1.shape[1]:
                    min_len = min(t0.shape[1], t1.shape[1])
                    t0 = t0[:, :min_len, :]
                    t1 = t1[:, :min_len, :]
                tensors = [t0, t1]
            return original_cat(tensors, dim=dim, **kw)
        torch.cat = safe_cat
        try:
            result = original_forward(self, *args, **kwargs)
        finally:
            torch.cat = original_cat
        return result
    prompt_model.EncDecHybridRNNTCTCBPEModelWithPrompt.forward = patched_forward

def load_model():
    model = nemo_asr.models.EncDecHybridRNNTCTCBPEModelWithPrompt.restore_from(
        MODEL_PATH, strict=False
    )
    model.eval()
    return model

def capture_audio(duration=3):
    print(f"Recording {duration}s from Tesira...")
    audio = sd.rec(
        int(duration * SAMPLE_RATE_IN),
        samplerate=SAMPLE_RATE_IN,
        channels=CHANNELS,
        dtype='int16',
        device=DEVICE
    )
    sd.wait()
    return audio.flatten().astype(np.float32) / 32768.0

def transcribe(model, audio_48k):
    audio_16k = signal.resample_poly(audio_48k, 1, 3)
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        sf.write(f.name, audio_16k, SAMPLE_RATE_OUT)
        result = model.transcribe([f.name])
    os.unlink(f.name)
    return result[0].text if hasattr(result[0], 'text') else str(result[0])

if __name__ == '__main__':
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    apply_patches()
    print("Loading NeMo ASR model...")
    model = load_model()
    print("Model ready.")
    audio = capture_audio(duration)
    text = transcribe(model, audio)
    print(f"\nTranscription: {text}")
