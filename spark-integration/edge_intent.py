"""
edge_intent.py — keyword/slot extraction for the Bernice Edge image skill.

Mirrors hdmi_intent.py: cheap regex matching, no LLM call, returns None when the
utterance is not an edge request so the routed loop falls through unchanged.
"""
import re

VERBS = r"(?:create|generate|make|draw|render|show(?: me)?|give me|paint|produce)"
NOUNS = r"(?:image|picture|visual|visualization|visualisation|illustration|diagram|graphic|drawing|rendering|scene)"
INTENT_RE = re.compile(
    rf"\b{VERBS}\b(?:\s+(?:me|us))?\s+(?:a|an|the|some)?\s*(?:\w+\s+)?{NOUNS}\s+(?:of|showing|that shows|about|for|depicting)\s+(?P<subject>.+)",
    re.I,
)
FILLER_RE = re.compile(r"^(?:bernice|hey bernice)[,\s]+|\s*(?:please|thanks|thank you)[.!?]*$", re.I)
MAX_SUBJECT = 300


def parse_edge_intent(utterance: str):
    """
    Returns {'operation': 'generate_image', 'subject': str} or None.

    Matches e.g. "create a visualization of how sound travels through a classroom",
    "show me an image of a coral reef", "make a quick diagram of the water cycle".
    """
    text = FILLER_RE.sub("", utterance.strip())
    m = INTENT_RE.search(text)
    if not m:
        return None
    subject = FILLER_RE.sub("", m.group("subject")).strip(" .!?,")
    if len(subject) < 3:
        return None
    return {"operation": "generate_image", "subject": subject[:MAX_SUBJECT]}
