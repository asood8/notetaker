"""Tab-separated export, for reviewing cards before importing them.

The leading `#` lines are Anki import directives. Recent versions read them and
configure the import dialog automatically, so the file imports correctly
without the user setting the separator, note type and tags column by hand.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from notetaker.models import Card, CardType


def write_tsv(cards: Sequence[Card], path: Path) -> Path:
    """Write `cards` to `path` as Anki-importable TSV."""
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = list(_header(cards))
    lines.extend(
        "\t".join((_field(card.question), _field(card.answer), " ".join(card.tags)))
        for card in cards
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _header(cards: Sequence[Card]) -> tuple[str, ...]:
    cloze = any(card.card_type is CardType.CLOZE for card in cards)
    return (
        "#separator:tab",
        "#html:true",
        f"#notetype:{'Cloze' if cloze else 'Basic'}",
        "#tags column:3",
    )


def _field(text: str) -> str:
    """Flatten a field so it survives a tab-separated, newline-delimited format."""
    return text.replace("\t", " ").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
