#!/usr/bin/env python3
"""
Bernice Overlay Server
- Serves overlay.html on port 8765
- WebSocket on port 8766 broadcasts state to connected overlays
- Reads state.json and pushes to clients on change
- Listens for TCP control commands on port 8767 (Vertex/external)
"""
import asyncio, json, os, time, threading, socket
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

STATE_FILE = Path(__file__).parent / 'state.json'
OVERLAY_DIR = Path(__file__).parent

DEFAULT_STATE = {
    "visible": True,
    "mode": "ambient",
    "status": "listening",
    "wake_detected": False,
    "heard": "",
    "response": "",
    "room_mode": "standby",
    "guide": {"title": "", "steps": [], "current": 0},
    "updated": 0
}

clients = set()
current_state = DEFAULT_STATE.copy()

def save_state():
    current_state["updated"] = time.time()
    STATE_FILE.write_text(json.dumps(current_state, indent=2))

def load_state():
    global current_state
    if STATE_FILE.exists():
        try:
            current_state = json.loads(STATE_FILE.read_text())
        except:
            current_state = DEFAULT_STATE.copy()

async def broadcast(data):
    if clients:
        msg = json.dumps(data)
        await asyncio.gather(*[ws.send(msg) for ws in list(clients)], return_exceptions=True)

async def ws_handler(websocket):
    clients.add(websocket)
    try:
        await websocket.send(json.dumps(current_state))
        async for msg in websocket:
            try:
                update = json.loads(msg)
                current_state.update(update)
                save_state()
                await broadcast(current_state)
            except:
                pass
    finally:
        clients.discard(websocket)

def update_state(updates: dict):
    current_state.update(updates)
    save_state()
    asyncio.run_coroutine_threadsafe(broadcast(current_state), loop)

def tcp_control_server():
    """Listen for Vertex TCP commands on port 8767"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('127.0.0.1', 8767))
        srv.listen(5)
        while True:
            try:
                conn, _ = srv.accept()
                with conn:
                    cmd = conn.recv(256).decode().strip()
                    handle_command(cmd)
                    conn.sendall(b'OK\n')
            except:
                pass

def handle_command(cmd):
    """Handle control commands from Vertex, voice loop, or external sources"""
    cmd = cmd.lower().strip()
    if cmd == 'show' or cmd == 'overlay on':
        update_state({"visible": True})
    elif cmd == 'hide' or cmd == 'overlay off':
        update_state({"visible": False})
    elif cmd == 'mode ambient':
        update_state({"mode": "ambient", "visible": True})
    elif cmd == 'mode response':
        update_state({"mode": "response", "visible": True})
    elif cmd == 'mode guide':
        update_state({"mode": "guide", "visible": True})
    elif cmd == 'mode full':
        update_state({"mode": "full", "visible": True})
    elif cmd.startswith('room '):
        update_state({"room_mode": cmd[5:]})
    elif cmd.startswith('json '):
        try:
            update_state(json.loads(cmd[5:]))
        except:
            pass

class OverlayHTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(OVERLAY_DIR), **kwargs)
    def log_message(self, *args): pass

async def main():
    global loop
    loop = asyncio.get_event_loop()
    load_state()

    try:
        import websockets
        ws_server = await websockets.serve(ws_handler, '0.0.0.0', 8766)
        print("WebSocket server on ws://0.0.0.0:8766")
    except ImportError:
        print("WARNING: websockets not installed - run: pip install websockets")
        ws_server = None

    http = HTTPServer(('0.0.0.0', 8765), OverlayHTTPHandler)
    http_thread = threading.Thread(target=http.serve_forever, daemon=True)
    http_thread.start()
    print("HTTP server on http://0.0.0.0:8765/overlay.html")

    tcp_thread = threading.Thread(target=tcp_control_server, daemon=True)
    tcp_thread.start()
    print("TCP control on 127.0.0.1:8767")

    print("Bernice Overlay Server running")
    if ws_server:
        await ws_server.wait_closed()
    else:
        await asyncio.sleep(99999)

if __name__ == '__main__':
    asyncio.run(main())
