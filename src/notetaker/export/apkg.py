"""Anki deck packages, via genanki.

The important detail here is identity. Anki decides whether an imported note
is new or an update by its GUID, so deriving the GUID from the question text
means re-running after editing your notes updates the existing cards instead
of leaving you with two near-identical copies of everything. The deck ID is
derived from the deck name for the same reason, and the note type ID is a
fixed constant because the note type itself never changes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import genanki

from notetaker.models import Card, CardType

MODEL_ID = 1_607_392_319
CLOZE_MODEL_ID = 1_607_392_320
"""Fixed: these note types are part of the tool, so they must not change between runs."""

MAX_ID = 2**31 - 1

CSS = """\
.card {
  font-family: -apple-system, Segoe UI, Roboto, sans-serif;
  font-size: 20px;
  text-align: center;
  color: #1a1a1a;
  background-color: #fdfdfd;
}
.answer { color: #0b5d3b; }
"""

MODEL = genanki.Model(
    MODEL_ID,
    "notetaker Basic",
    fields=[{"name": "Question"}, {"name": "Answer"}],
    templates=[
        {
            "name": "Card 1",
            "qfmt": "{{Question}}",
            "afmt": '{{FrontSide}}<hr id="answer"><div class="answer">{{Answer}}</div>',
        }
    ],
    css=CSS,
)

CLOZE_CSS = (
    CSS
    + """\
.cloze { font-weight: bold; color: #0b5d3b; }
"""
)

CLOZE_MODEL = genanki.Model(
    CLOZE_MODEL_ID,
    "notetaker Cloze",
    fields=[{"name": "Text"}, {"name": "Back Extra"}],
    templates=[
        {
            "name": "Cloze",
            "qfmt": "{{cloze:Text}}",
            "afmt": '{{cloze:Text}}<br><div class="answer">{{Back Extra}}</div>',
        }
    ],
    css=CLOZE_CSS,
    model_type=genanki.Model.CLOZE,
)


def write_apkg(cards: Sequence[Card], path: Path, deck_name: str) -> Path:
    """Write `cards` to `path` as an Anki deck package."""
    path.parent.mkdir(parents=True, exist_ok=True)

    deck = genanki.Deck(stable_id(deck_name), deck_name)
    for card in cards:
        deck.add_note(
            genanki.Note(
                model=_model_for(card),
                fields=[card.question, card.answer],
                tags=list(card.tags),
                guid=genanki.guid_for(card.question),
            )
        )

    genanki.Package(deck).write_to_file(str(path))
    return path


def _model_for(card: Card) -> genanki.Model:
    return CLOZE_MODEL if card.card_type is CardType.CLOZE else MODEL


def stable_id(text: str) -> int:
    """A deterministic Anki ID for `text`.

    Anki IDs are signed 32-bit, so the hash is folded into that range. The
    same name must always produce the same ID, which rules out `hash()`.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % MAX_ID + 1
