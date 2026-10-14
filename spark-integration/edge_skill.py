"""
edge_skill.py — routed-loop skill that delegates image jobs to the Bernice Edge node.

Called from bernice-routed-loop.py when parse_edge_intent() matches and
BERNICE_EDGE_ENABLED=1. Submits the job and returns at once with a spoken
acknowledgement; a background thread follows the job and publishes progress to
the overlay, so the voice loop is never blocked by generation.
"""
import os
import threading
import time

import edge_client

ENABLED = os.environ.get("BERNICE_EDGE_ENABLED", "0") == "1"
JOB_TIMEOUT_S = int(os.environ.get("EDGE_JOB_TIMEOUT_S", "180"))
SESSION_ID = os.environ.get("EDGE_SESSION_ID", "xrt-room-01")


def _follow(job_id, subject, overlay, log):
    t0 = time.time()
    last = None
    while time.time() - t0 < JOB_TIMEOUT_S:
        try:
            job = edge_client.call("GET", f"/jobs/{job_id}")
        except Exception as e:  # noqa: BLE001 - network blips must not kill the thread
            log.info(f"Edge poll error for {job_id}: {e}")
            time.sleep(2)
            continue
        status = job.get("status")
        if status != last or status == "running":
            overlay({"edge_job": {"job_id": job_id, "subject": subject, "status": status,
                                  "progress": job.get("progress", 0.0)}})
            last = status
        if status in ("completed", "failed", "cancelled", "rejected"):
            ms = round((time.time() - t0) * 1000)
            log.info(f"Edge job {job_id} {status} in {ms} ms (model={job.get('model')}, device={job.get('device')})")
            return
        time.sleep(0.5)
    overlay({"edge_job": {"job_id": job_id, "subject": subject, "status": "timed_out"}})
    log.info(f"Edge job {job_id} timed out after {JOB_TIMEOUT_S} s")


def handle_edge(intent, overlay, log):
    """Returns the sentence Bernice should speak."""
    subject = intent["subject"]
    t0 = time.time()
    try:
        acc = edge_client.generate_image(subject, session_id=SESSION_ID, wait=False)
    except Exception as e:  # noqa: BLE001
        log.info(f"Edge unreachable: {e}")
        return "I can't reach the room display node right now, so I can't make that image."
    if acc.get("status") != "queued":
        log.info(f"Edge rejected job: {acc}")
        if acc.get("http_error") == 429:
            return "The display node is busy with other images. Try again in a moment."
        return "The display node didn't accept that request."
    job_id = acc["job_id"]
    log.info(f"Edge job {job_id} accepted in {round((time.time() - t0) * 1000)} ms: {subject[:60]}")
    threading.Thread(target=_follow, args=(job_id, subject, overlay, log), daemon=True).start()
    return f"Sure. I'm generating an image of {subject} on the room display."
