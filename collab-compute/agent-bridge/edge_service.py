#!/usr/bin/env python3
"""Bernice Edge job service (Sprint 1 skeleton).

Runs on the Crestron Collab Compute. Exposes a small, authenticated HTTP API
that the Spark calls to delegate visual tasks. Standard library only.

Image generation uses OpenVINO GenAI (Text2ImagePipeline) on the Intel GPU when
EDGE_MODEL points at an OpenVINO diffusion model folder. Without it, or if the
model fails to load, a test-pattern generator keeps the API working.

Endpoints (all require: Authorization: Bearer <EDGE_TOKEN>)
  GET  /status                 health, devices, job counts
  POST /jobs/generate_image    {"prompt": str, "width": int, "height": int, "session_id": str}
  GET  /jobs/<job_id>          job state
  POST /jobs/<job_id>/cancel   cancel a queued job
  GET  /artifacts/<job_id>     finished PNG

Configuration (environment, normally from ~/.config/bernice-edge/edge.env):
  EDGE_TOKEN   required shared secret
  EDGE_BIND    address to listen on (default 127.0.0.1; set to the edge's
               Tailscale address so only the tailnet can reach it)
  EDGE_PORT    default 8790
  EDGE_DATA    artifact/job directory (default ~/.local/share/bernice-edge)
  EDGE_MODEL   OpenVINO diffusion model folder (optional; e.g. ~/models/sd15-int8-ov)
  EDGE_DEVICE  OpenVINO device for generation (default GPU)
  EDGE_STEPS   inference steps (default 20)
  EDGE_DISPLAY_PORT  room display page on 127.0.0.1 only (default 8791; no token,
               read-only: current job progress and finished images)
"""

import hmac
import json
import os
import queue
import socket
import struct
import threading
import time
import uuid
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "0.3.0-display"
TOKEN = os.environ.get("EDGE_TOKEN", "")
BIND = os.environ.get("EDGE_BIND", "127.0.0.1")
PORT = int(os.environ.get("EDGE_PORT", "8790"))
DATA = Path(os.environ.get("EDGE_DATA", Path.home() / ".local/share/bernice-edge"))
ART = DATA / "artifacts"
MODEL_DIR = os.path.expanduser(os.environ.get("EDGE_MODEL", ""))
GEN_DEVICE = os.environ.get("EDGE_DEVICE", "GPU")
STEPS = max(1, min(int(os.environ.get("EDGE_STEPS", "20")), 50))
DISPLAY_PORT = int(os.environ.get("EDGE_DISPLAY_PORT", "8791"))
DISPLAY_HTML = Path(__file__).resolve().parent.parent / "ui" / "display.html"

MAX_PROMPT = 1000
SIZES = (256, 512, 768)
MAX_QUEUE = 8
STARTED = time.time()

jobs = {}
jobs_lock = threading.Lock()
work = queue.Queue(maxsize=MAX_QUEUE)
gen = {"model": "dummy-test-pattern", "device": "CPU", "state": "dummy", "pipe": None, "warm_s": None}


def log(msg, **kw):
    print(json.dumps({"t": round(time.time(), 3), "msg": msg, **kw}), flush=True)


def devices():
    try:
        import openvino as ov  # optional; present in the edge venv
        return ov.Core().available_devices
    except Exception as e:  # noqa: BLE001
        return [f"unavailable: {type(e).__name__}"]


def test_pattern_png(w, h, seed):
    """Small gradient PNG built with zlib, so Sprint 1 needs no image libs."""
    r0, g0 = seed % 256, (seed * 7) % 256
    rows = bytearray()
    for y in range(h):
        rows.append(0)
        for x in range(w):
            rows += bytes(((r0 + x) % 256, (g0 + y) % 256, (x * y) % 256))

    def chunk(kind, body):
        c = kind + body
        return struct.pack(">I", len(body)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b"")


def load_generator():
    """Load the OpenVINO pipeline once, in the worker thread, and warm it up."""
    if not MODEL_DIR:
        log("generator.dummy", reason="EDGE_MODEL not set")
        return
    gen["state"] = "loading"
    t0 = time.time()
    try:
        import openvino_genai as ovg
        pipe = ovg.Text2ImagePipeline(MODEL_DIR, GEN_DEVICE)
        pipe.generate("warm up", width=512, height=512, num_inference_steps=1)
        gen.update(pipe=pipe, model=Path(MODEL_DIR).name, device=GEN_DEVICE, state="ready",
                   warm_s=round(time.time() - t0, 1))
        log("generator.ready", model=gen["model"], device=GEN_DEVICE, warm_s=gen["warm_s"])
    except Exception as e:  # noqa: BLE001 - fall back so the API stays usable
        gen.update(state="failed", error=f"{type(e).__name__}: {e}")
        log("generator.failed", error=gen["error"])


def render(job_id, prompt, w, h):
    """Returns PNG bytes. Uses the OpenVINO pipeline when ready, else the test pattern."""
    pipe = gen["pipe"]
    if pipe is None:
        for i in range(1, 5):
            time.sleep(0.5)
            update(job_id, progress=i / 4)
        return test_pattern_png(w, h, hash(prompt) & 0xFFFF)
    import io
    from PIL import Image

    def on_step(step, num_steps, _latent):
        update(job_id, progress=round((step + 1) / max(num_steps, 1), 3))
        return False  # False = keep going

    try:
        result = pipe.generate(prompt, width=w, height=h, num_inference_steps=STEPS, callback=on_step)
    except TypeError:  # older GenAI builds without the callback argument
        result = pipe.generate(prompt, width=w, height=h, num_inference_steps=STEPS)
    buf = io.BytesIO()
    Image.fromarray(result.data[0]).save(buf, format="PNG")
    return buf.getvalue()


def update(job_id, **fields):
    with jobs_lock:
        jobs[job_id].update(fields)


def worker():
    load_generator()
    while True:
        job_id = work.get()
        with jobs_lock:
            job = dict(jobs[job_id])
        if job["status"] == "cancelled":
            continue
        update(job_id, status="running", started=time.time(), progress=0.0)
        log("job.running", job_id=job_id)
        try:
            png = render(job_id, job["prompt"], job["width"], job["height"])
            (ART / f"{job_id}.png").write_bytes(png)
            update(job_id, status="completed", finished=time.time(), artifact_id=job_id,
                   model=gen["model"], device=gen["device"], steps=STEPS if gen["pipe"] else 0,
                   progress=1.0)
            log("job.completed", job_id=job_id, model=gen["model"],
                seconds=round(time.time() - jobs[job_id]["started"], 1))
        except Exception as e:  # noqa: BLE001
            update(job_id, status="failed", finished=time.time(), error=str(e))
            log("job.failed", job_id=job_id, error=str(e))


class Handler(BaseHTTPRequestHandler):
    server_version = f"bernice-edge/{VERSION}"

    def log_message(self, fmt, *args):
        log("http", client=self.client_address[0], line=fmt % args)

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        got = self.headers.get("Authorization", "")
        ok = bool(TOKEN) and hmac.compare_digest(got, f"Bearer {TOKEN}")
        if not ok:
            self.send_json(401, {"error": "unauthorized"})
        return ok

    def do_GET(self):
        if not self.authorized():
            return
        parts = self.path.strip("/").split("/")
        if parts == ["status"]:
            with jobs_lock:
                counts = {}
                for j in jobs.values():
                    counts[j["status"]] = counts.get(j["status"], 0) + 1
            return self.send_json(200, {
                "service": "bernice-edge", "version": VERSION, "host": socket.gethostname(),
                "uptime_s": round(time.time() - STARTED), "devices": devices(),
                "queue_depth": work.qsize(), "queue_capacity": MAX_QUEUE, "jobs": counts,
                "models": [gen["model"]], "generator": {k: gen.get(k) for k in ("model", "device", "state", "warm_s", "error")},
                "steps": STEPS,
            })
        if len(parts) == 2 and parts[0] == "jobs":
            with jobs_lock:
                job = jobs.get(parts[1])
            return self.send_json(200, job) if job else self.send_json(404, {"error": "no such job"})
        if len(parts) == 2 and parts[0] == "artifacts":
            name = parts[1]
            path = ART / f"{name}.png"
            if not name.replace("-", "").isalnum() or not path.is_file():
                return self.send_json(404, {"error": "no such artifact"})
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self.authorized():
            return
        parts = self.path.strip("/").split("/")
        if parts == ["jobs", "generate_image"]:
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n > 16384:
                    return self.send_json(413, {"error": "request too large"})
                req = json.loads(self.rfile.read(n) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self.send_json(400, {"error": "invalid JSON"})
            prompt = str(req.get("prompt", "")).strip()
            w, h = req.get("width", 512), req.get("height", 512)
            if not prompt or len(prompt) > MAX_PROMPT:
                return self.send_json(400, {"error": f"prompt required, max {MAX_PROMPT} chars"})
            if w not in SIZES or h not in SIZES:
                return self.send_json(400, {"error": f"width/height must be one of {SIZES}"})
            job_id = f"img-{uuid.uuid4().hex[:10]}"
            job = {"job_id": job_id, "operation": "generate_image", "status": "queued",
                   "session_id": str(req.get("session_id", "default"))[:64],
                   "request_id": str(req.get("request_id", ""))[:64],
                   "prompt": prompt, "width": w, "height": h, "progress": 0.0,
                   "created": time.time()}
            with jobs_lock:
                jobs[job_id] = job
            try:
                work.put_nowait(job_id)
            except queue.Full:
                update(job_id, status="rejected", error="queue full")
                return self.send_json(429, {"job_id": job_id, "status": "rejected", "error": "queue full"})
            log("job.accepted", job_id=job_id)
            return self.send_json(202, {"event": "edge.job.accepted", "job_id": job_id, "status": "queued"})
        if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "cancel":
            with jobs_lock:
                job = jobs.get(parts[1])
                if not job:
                    return self.send_json(404, {"error": "no such job"})
                if job["status"] != "queued":
                    return self.send_json(409, {"job_id": parts[1], "status": job["status"], "error": "only queued jobs can be cancelled"})
                job["status"] = "cancelled"
            return self.send_json(200, {"job_id": parts[1], "status": "cancelled"})
        self.send_json(404, {"error": "not found"})


def display_state():
    """What the room display needs: the job in progress and the latest finished image."""
    with jobs_lock:
        js = list(jobs.values())
    running = [j for j in js if j["status"] in ("running", "queued")]
    done = [j for j in js if j["status"] == "completed"]
    active = min(running, key=lambda j: j["created"]) if running else None
    latest = max(done, key=lambda j: j["finished"]) if done else None
    return {
        "active": active and {k: active.get(k) for k in ("job_id", "prompt", "status", "progress")},
        "latest": latest and {"artifact_id": latest["artifact_id"], "prompt": latest["prompt"],
                              "model": latest.get("model"), "device": latest.get("device"),
                              "width": latest["width"], "height": latest["height"],
                              "seconds": round(latest["finished"] - latest["started"], 1)},
    }


class DisplayHandler(Handler):
    """Read-only, unauthenticated, bound to 127.0.0.1 for the local kiosk browser."""

    def do_GET(self):
        parts = self.path.split("?")[0].strip("/").split("/")
        if parts in (["display"], [""]):
            data = DISPLAY_HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if parts == ["display", "state"]:
            return self.send_json(200, display_state())
        if len(parts) == 3 and parts[:2] == ["display", "artifacts"] and parts[2].endswith(".png"):
            name = parts[2][:-4]
            path = ART / f"{name}.png"
            if not name.replace("-", "").isalnum() or not path.is_file():
                return self.send_json(404, {"error": "no such artifact"})
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        self.send_json(405, {"error": "read-only"})

    def log_message(self, fmt, *args):
        pass  # the kiosk polls every second; keep the journal readable


def main():
    if len(TOKEN) < 24:
        raise SystemExit("EDGE_TOKEN must be set (24+ characters). See collab-compute/README.md.")
    ART.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=worker, daemon=True).start()
    display = ThreadingHTTPServer(("127.0.0.1", DISPLAY_PORT), DisplayHandler)
    threading.Thread(target=display.serve_forever, daemon=True).start()
    log("starting", bind=BIND, port=PORT, display=f"127.0.0.1:{DISPLAY_PORT}", version=VERSION)
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
