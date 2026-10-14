#!/usr/bin/env python3
"""Spark-side client for the Bernice Edge job service (Sprint 1).

Used as a CLI test now, and imported by the routed-loop edge skill later.

  edge_client.py status
  edge_client.py generate "a diagram of sound waves in a lecture hall"

Configuration (environment, normally sourced from ~/.env_secrets):
  EDGE_URL    e.g. http://bernice-edge-01:8790
  EDGE_TOKEN  same shared secret as the edge
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = os.environ.get("EDGE_URL", "http://bernice-edge-01:8790").rstrip("/")
TOKEN = os.environ.get("EDGE_TOKEN", "")


def call(method, path, body=None, raw=False, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            return payload if raw else json.loads(payload)
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, **json.loads(e.read() or b"{}")}


def status():
    return call("GET", "/status")


def generate_image(prompt, width=512, height=512, session_id="spark", wait=True, timeout_s=120):
    t0 = time.time()
    acc = call("POST", "/jobs/generate_image",
               {"prompt": prompt, "width": width, "height": height, "session_id": session_id})
    if "job_id" not in acc or not wait:
        return acc
    ack_ms = round((time.time() - t0) * 1000)
    while time.time() - t0 < timeout_s:
        job = call("GET", f"/jobs/{acc['job_id']}")
        if job.get("status") in ("completed", "failed", "cancelled", "rejected"):
            job["ack_ms"] = ack_ms
            job["total_ms"] = round((time.time() - t0) * 1000)
            return job
        time.sleep(0.5)
    return {"job_id": acc["job_id"], "status": "timed_out", "ack_ms": ack_ms}


def fetch_artifact(artifact_id, dest):
    data = call("GET", f"/artifacts/{artifact_id}", raw=True)
    if isinstance(data, dict):
        return data
    with open(dest, "wb") as f:
        f.write(data)
    return {"saved": dest, "bytes": len(data)}


if __name__ == "__main__":
    if not TOKEN:
        sys.exit("EDGE_TOKEN not set. Source ~/.env_secrets first.")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(status(), indent=2))
    elif cmd == "generate":
        job = generate_image(" ".join(sys.argv[2:]) or "test pattern")
        print(json.dumps(job, indent=2))
        if job.get("status") == "completed":
            print(json.dumps(fetch_artifact(job["artifact_id"], f"/tmp/{job['artifact_id']}.png")))
    else:
        sys.exit(__doc__)
