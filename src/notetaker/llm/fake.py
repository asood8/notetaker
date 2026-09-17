"""A deterministic stand-in for a real model.

This exists for two reasons. It lets the test suite exercise the whole
pipeline in CI without Ollama, and it gives anyone who clones the repo a way
to see the tool work before downloading several gigabytes of weights.

It is a crude sentence matcher, not a model. The cards it writes are only
about as good as the sentences it found.
"""

from __future__ import annotations

import re
from typing import Any

from notetaker.prompts import extract_notes

DEFINITION_RE = re.compile(r"^(.{3,80}?)\s+(is|are)\s+(.{10,})$", re.IGNORECASE)
COLON_RE = re.compile(r"^(.{3,80}?):\s+(.{10,})$")
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class FakeLLM:
    """Builds cards from `X is Y` and `X: Y` sentences."""

    name = "fake"

    def __init__(self, max_cards: int = 8) -> None:
        self.max_cards = max_cards

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        cards: list[dict[str, str]] = []

        for line in _logical_lines(extract_notes(user)):
            for sentence in SENTENCE_RE.split(line):
                if len(cards) >= self.max_cards:
                    return {"cards": cards}
                card = _to_card(sentence.strip())
                if card is not None:
                    cards.append(card)

        return {"cards": cards}


def _logical_lines(notes: str) -> list[str]:
    """Undo hard wrapping so a definition split across lines stays one sentence.

    A new logical line starts at a bullet or after a blank line; anything else
    is a continuation of the line above.
    """
    lines: list[str] = []

    for raw in notes.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith(("#", "```", "~~~", "|")):
            lines.append("")
            continue
        if BULLET_RE.match(raw) or not lines or not lines[-1]:
            lines.append(BULLET_RE.sub("", stripped))
        else:
            lines[-1] = f"{lines[-1]} {stripped}"

    return [line for line in lines if line]


def _to_card(sentence: str) -> dict[str, str] | None:
    colon = COLON_RE.match(sentence)
    if colon is not None:
        term, definition = colon.group(1), colon.group(2)
        return {"question": f"What is {term.strip()}?", "answer": _tidy(definition)}

    definition = DEFINITION_RE.match(sentence)
    if definition is not None:
        term, verb, rest = definition.group(1), definition.group(2), definition.group(3)
        article = "are" if verb.lower() == "are" else "is"
        return {"question": f"What {article} {term.strip()}?", "answer": _tidy(rest)}

    return None


def _tidy(text: str) -> str:
    return text.strip().rstrip(".").strip() or "(no answer found)"
