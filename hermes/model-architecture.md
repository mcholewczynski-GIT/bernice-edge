# Bernice Model Architecture

## Two-Tier Inference Stack (Confirmed July 19, 2026)

### Tier 1 — Conversational Router
- Model: `nemotron-mini:latest` (Nemotron-Mini-4B-Instruct)
- Warm latency: ~0.5s
- Memory: 3.4GB GPU
- Role: All incoming requests. Simple conversational queries answered directly.
  Complex queries trigger bridging phrase via TTS, then hand off to Tier 2.

### Tier 2 — Deep Reasoner
- Model: `bernice-llm:latest` (Nemotron 3 Super 120B Q4_K_M, custom Modelfile)
- Warm latency: ~12s
- Memory: 85GB GPU
- Role: Hardware control, data visualization, multi-step agentic tasks,
  anything requiring deep reasoning or skill execution.

## Co-Residency
- Total GPU memory: 88.4GB (fits within 128GB unified memory)
- Swap impact: ~977MB (stable, not growing)
- Both models loaded with keep_alive=-1 (permanent residency)

## Routing Handoff Phrases (TTS playback while Tier 2 generates)
- "Great question — let me dig into that for you."
- "That needs a bit more thought. Give me just a moment."
- "I'll pull that together for you now."

## Models Evaluated and Rejected
- llama3.1:8b — 0.77s warm but Meta stack, not NVIDIA
- nemotron-3-nano — 4-6s warm, too slow for router role; 24GB too large for
  co-residency with both Mini and Super simultaneously
- Three-model co-residency (Mini + Nano + Super) — not viable on 128GB;
  Ollama evicts smaller models when Super loads

## Startup Sequence
Both models must be explicitly warmed after Ollama restarts:
```bash
curl -s http://localhost:11434/api/generate -d '{"model":"bernice-llm","keep_alive":-1,"prompt":""}' > /dev/null
curl -s http://localhost:11434/api/generate -d '{"model":"nemotron-mini","keep_alive":-1,"prompt":""}' > /dev/null
```
