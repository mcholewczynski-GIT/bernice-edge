"""
hdmi_intent.py — keyword/slot extraction for the HDMI routing skill
"""
import re

TRIGGER_WORDS = ("switch", "show me", "route", "change to", "send to", "put")
INPUT_RE = re.compile(r"input\s*(one|two|three|four|1|2|3|4)\b", re.I)
OUTPUT_RE = re.compile(r"output\s*(one|two|1|2)\b", re.I)
WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4}

def _to_num(token: str) -> int:
    return WORD_NUM.get(token.lower()) or int(token)

def parse_hdmi_intent(utterance: str) -> dict:
    """
    Returns dict with 'input' and 'output' keys, or None if not an HDMI command.
    'output' may be None if not specified (requires disambiguation).
    """
    text = utterance.lower()
    if not any(t in text for t in TRIGGER_WORDS):
        return None
    in_match = INPUT_RE.search(text)
    if not in_match:
        return None
    out_match = OUTPUT_RE.search(text)
    return {
        "input": _to_num(in_match.group(1)),
        "output": _to_num(out_match.group(1)) if out_match else None,
    }
