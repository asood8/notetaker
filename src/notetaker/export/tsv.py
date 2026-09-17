"""Tab-separated export, for reviewing cards before importing them.

The leading `#` lines are Anki import directives. Recent versions read them
and configure the import dialog automatically, so the file imports correctly
without the user setting the separator and tags column by hand.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from notetaker.models import Card

HEADER = (
    "#separator:tab",
    "#html:true",
    "#notetype:Basic",
    "#tags column:3",
)


def write_tsv(cards: Sequence[Card], path: Path) -> Path:
    """Write `cards` to `path` as Anki-importable TSV."""
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = list(HEADER)
    lines.extend(
        "\t".join((_field(card.question), _field(card.answer), " ".join(card.tags)))
        for card in cards
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _field(text: str) -> str:
    """Flatten a field so it survives a tab-separated, newline-delimited format."""
    return text.replace("\t", " ").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
