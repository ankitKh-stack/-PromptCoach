"""Code-level checks for banned patterns in a final prompt (patterns live in config.yaml)."""
import re

from coach.config import load_config

_PLACEHOLDER = re.compile(r"\[[^\]\n]*\]")


def find_caps_emphasis(text: str) -> list[str]:
    words = load_config()["lint"]["caps_emphasis_words"]
    stripped = _PLACEHOLDER.sub(" ", text)
    hits = []
    for word in words:
        if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", stripped):
            hits.append(word)
    return hits


def find_patterns(text: str, key: str) -> list[str]:
    hits = []
    for pattern in load_config()["lint"][key]:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            hits.append(m.group(0))
    return hits


def lint(text: str, reasoning_target: bool) -> dict:
    """Return {'caps': [...], 'pressure': [...], 'step_by_step': [...]} of matched snippets."""
    return {
        "caps": find_caps_emphasis(text),
        "pressure": find_patterns(text, "tip_threat_patterns"),
        # Avoided for every target; only counted as a failure for reasoning targets.
        "step_by_step": find_patterns(text, "step_by_step_patterns") if reasoning_target else [],
    }
