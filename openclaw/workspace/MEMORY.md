# MEMORY

## Infrastructure
- Ollama: http://127.0.0.1:11434
- ComfyUI: http://127.0.0.1:8188
- Gateway: ws://127.0.0.1:18789
- NAS: //nas.xrt.oregonstate.edu/shared

## Models
- Primary LLM: nemotron-3-super
- STT live: distil-large-v3
- Previous LLM: gpt-oss:120b (replaced March 2026)

## Rules
- Exec mode: full (dev only)
- Hardware confirmation required: DMX, Crestron, audio master
- Port 18789 via SSH tunnel only

## Security Trip Wire — Pre-Multi-User Checklist
Added: 2026-03-12

The following MUST be completed before any second user accesses Bernice.
Do not proceed with onboarding additional operators until all three are done.

- [ ] dmScope: change from 'main' to 'per-channel-peer' in config.json
- [ ] execMode: change from 'full' to 'gateway' in config.json
- [ ] exec-approvals.json: define whitelist of approved shell commands

If asked about multi-user readiness, always reference this checklist first.

## Render Node
- Hostname: sneed.ceoas.oregonstate.edu
- IP: 10.129.222.178
- OpenCLAW node ID: delluser-Precision-5860-Tower
- GPU 0 (render): RTX 6000 Ada 48GB — ComfyUI port 8188
- GPU 1 (display): RTX 6000 Ada 48GB — MPV IPC /tmp/mpv-socket
- Models installed: sd_xl_base_1.0.safetensors, sd_xl_refiner_1.0.safetensors
- Storage: /mnt/xrt/ — models, renders, playout
- ComfyUI API: http://sneed.ceoas.oregonstate.edu:8188
- Render wrapper: python3 ~/comfyui_render.py "prompt" (run as cholewcm on sneed)
- Playout trigger: socat IPC to /tmp/mpv-socket on sneed
- ComfyUI web: http://sneed.ceoas.oregonstate.edu:8188

## Render Models — Updated April 21 2026
- flux1-dev-fp8.safetensors: /mnt/xrt/models/checkpoints/ — high quality, use for final wall renders
- flux1-schnell-fp8.safetensors: /mnt/xrt/models/checkpoints/ — fast iteration renders
- sd_xl_base_1.0.safetensors: /mnt/xrt/models/checkpoints/ — fallback only
- sd_xl_refiner_1.0.safetensors: /mnt/xrt/models/checkpoints/ — fallback only
- Default model: flux1-dev-fp8 for quality, flux1-schnell-fp8 for speed

## Render Router
- Skill file: ~/.openclaw/skills/render_router.md
- Use render_router skill for ALL render and visualization requests
- Router decides pipeline: ComfyUI, Blender, or data interpreter
- Data files drop zone: /mnt/xrt/data/incoming/ on sneed

## Data Visualization — P1 Complete
- data_interpreter.py: BUILT — ~/data_interpreter.py on sneed
- chart_render.py: BUILT — ~/chart_render.py on sneed
- Supported input formats: CSV, XML, XLS, JSON
- Chart types: line, bar, scatter, heatmap — auto-detected from data
- Output: 8K dark-theme PNG to /mnt/xrt/renders/comfyui/
- Workflow: interpreter → processed JSON → chart_render → wall
- Blender headless pipeline: NOT YET WIRED — coming P2

## Render Wrapper
- comfyui_render.py: v3 — supports FLUX + SDXL with auto model profiles
- Default model: flux1-dev-fp8.safetensors
- FLUX profile: cfg=1.0, steps=20, scheduler=simple
- Schnell profile: cfg=1.0, steps=4, scheduler=simple
- SDXL profile: cfg=7.0, steps=20, scheduler=normal
