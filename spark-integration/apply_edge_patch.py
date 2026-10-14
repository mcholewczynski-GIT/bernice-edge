#!/usr/bin/env python3
"""Add the Bernice Edge hooks to a routed-loop file in place.

Used instead of copying the repo's bernice-routed-loop.py over the live one,
because the live file can carry changes that are not in the repo.

  python3 apply_edge_patch.py /home/admin/bernice-routed-loop.py

Idempotent: running it twice changes nothing. Writes nothing unless both
anchor lines are found exactly once. Keep a backup before running.
"""
import py_compile
import sys

MARK = "# Bernice Edge skill (Crestron Collab Compute)."

IMPORT_ANCHOR = "from hdmi_switch import switch_input, get_all_routes, SwitcherError\n"
IMPORT_BLOCK = MARK + """ Off unless BERNICE_EDGE_ENABLED=1;
# if the modules are missing the loop runs exactly as before.
try:
    from edge_intent import parse_edge_intent
    from edge_skill import handle_edge, ENABLED as EDGE_ENABLED
except ImportError:
    EDGE_ENABLED = False
"""

HANDLE_ANCHOR = "    if is_xrt(text):\n"
HANDLE_BLOCK = """    # Bernice Edge: delegate image requests to the Collab Compute
    edge_intent = parse_edge_intent(text) if EDGE_ENABLED else None
    if edge_intent is not None:
        log.info(f'Edge intent: {edge_intent}')
        resp = handle_edge(edge_intent, overlay, log)
        log.info(f'Bernice: {resp}')
        tts(strip_markdown(resp))
        overlay({'response': resp, 'status': 'speaking', 'mode': 'response'})
        time.sleep(max(1.0, len(resp.split()) * 0.3))
        overlay({'status': 'listening', 'wake_detected': False, 'mode': 'ambient'})
        return
"""


def main(path):
    src = open(path).read()
    if MARK in src:
        print("Already patched; no change.")
        return
    for name, anchor in (("import", IMPORT_ANCHOR), ("handle", HANDLE_ANCHOR)):
        n = src.count(anchor)
        if n != 1:
            sys.exit(f"Stopped: {name} anchor found {n} times (expected 1). File not changed.")
    out = src.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_BLOCK).replace(HANDLE_ANCHOR, HANDLE_BLOCK + HANDLE_ANCHOR)
    tmp = path + ".edge-tmp"
    open(tmp, "w").write(out)
    py_compile.compile(tmp, doraise=True)
    import os
    os.replace(tmp, path)
    print(f"Patched {path} (+{out.count(chr(10)) - src.count(chr(10))} lines).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
