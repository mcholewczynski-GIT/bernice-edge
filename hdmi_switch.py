"""
hdmi_switch.py — Bernice skill module for DigitaLinx DL-S42-H2
POC scope: inputs 1-4 -> outputs 1-2 over Telnet (TCP 23)
"""
import socket

DL_S42_IP = "10.160.223.226"
DL_S42_PORT = 23
TIMEOUT_SEC = 2.0

class SwitcherError(Exception):
    pass

def _send(cmd: str) -> str:
    """Open a short-lived TCP connection, send one command, read one reply."""
    try:
        with socket.create_connection((DL_S42_IP, DL_S42_PORT), timeout=TIMEOUT_SEC) as sock:
            sock.sendall(f"{cmd}\r\n".encode("ascii"))
            sock.settimeout(TIMEOUT_SEC)
            raw = b""
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                raw += chunk
                # Stop once we get a line ending
                if b"\r\n" in raw[raw.find(b"\r\n", raw.find(b"Matrix!\r\n") + 9 if b"Matrix" in raw else 0):]:
                    break
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        raise SwitcherError(f"DL-S42-H2 unreachable: {exc}") from exc
    # Strip the welcome banner and return just the command response
    lines = raw.decode("ascii", errors="ignore").strip().split("\r\n")
    for line in lines:
        if line and not line.startswith("Welcome"):
            return line.strip()
    return ""

def switch_input(input_num: int, output_num: int) -> bool:
    """Route HDMI IN{input_num} to HDMI OUT{output_num}. Returns True on confirmed switch."""
    if input_num not in (1, 2, 3, 4):
        raise ValueError("input_num must be 1-4")
    if output_num not in (1, 2):
        raise ValueError("output_num must be 1 or 2")
    cmd = f"SET SW in{input_num} out{output_num}"
    reply = _send(cmd)
    expected = f"SW in{input_num} out{output_num}"
    return reply.strip() == expected

def get_route(output_num: int):
    """Query which input is currently routed to the given output. Returns input number or None."""
    reply = _send(f"GET MP out{output_num}")
    parts = reply.split()
    if len(parts) >= 2 and parts[1].upper().startswith("IN"):
        return int(parts[1][2:])
    return None

def get_all_routes() -> dict:
    """Return current routing state for both outputs."""
    return {1: get_route(1), 2: get_route(2)}
