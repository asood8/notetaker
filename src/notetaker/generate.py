"""Drive chunks through a model and collect validated cards."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from pydantic import ValidationError

from notetaker.chunking import Chunk
from notetaker.dedup import Deduper
from notetaker.llm.base import LLMClient, LLMError
from notetaker.models import Card
from notetaker.prompts import build_prompt
from notetaker.quality import is_admin_section, rejection_reason
from notetaker.styles import BASIC, Style

DEFAULT_MAX_CARDS_PER_CHUNK = 8


@dataclass
class Rejected:
    """A card that was thrown away, and why."""

    card: Card
    reason: str
    tag: str = ""


@dataclass
class GenerationResult:
    """Cards, plus what went wrong along the way."""

    cards: list[Card] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    duplicates: int = 0
    low_quality: int = 0
    skipped_sections: int = 0
    unsupported: int = 0
    invalid_responses: int = 0
    failed_chunks: int = 0


def generate_cards(
    chunks: Iterable[Chunk],
    client: LLMClient,
    *,
    style: Style = BASIC,
    max_cards_per_chunk: int = DEFAULT_MAX_CARDS_PER_CHUNK,
    extra_tags: Iterable[str] = (),
    check: Callable[[list[Card], str], list[bool]] | None = None,
    on_chunk: Callable[[Chunk, int], None] | None = None,
) -> GenerationResult:
    """Generate cards for every chunk, skipping anything the model gets wrong.

    A bad response for one chunk should never lose the cards from the others,
    so failures are counted and reported rather than raised.
    """
    result = GenerationResult()
    deduper = Deduper()
    shared_tags = list(extra_tags)
    schema = style.batch.model_json_schema()

    for chunk in chunks:
        # Course admin is recognised from the heading, so the model is never
        # asked about it. Cheaper than generating cards and throwing them away,
        # and it keeps exam dates out of the deck entirely.
        if is_admin_section(chunk.heading_path):
            result.skipped_sections += 1
            _report(on_chunk, chunk, 0)
            continue

        system, user = build_prompt(
            chunk,
            max_cards_per_chunk,
            system=style.system,
            template=style.template,
        )

        try:
            raw = client.complete(system, user, schema)
        except LLMError:
            result.failed_chunks += 1
            _report(on_chunk, chunk, 0)
            continue

        try:
            batch = style.batch.model_validate(raw)
        except ValidationError:
            result.invalid_responses += 1
            _report(on_chunk, chunk, 0)
            continue

        cards = style.to_cards(batch)
        result.low_quality += len(batch.cards) - len(cards)
        cards = cards[:max_cards_per_chunk]

        if check is not None and cards:
            supported = check(cards, chunk.text)
            kept = []
            for card, ok in zip(cards, supported, strict=False):
                if ok:
                    kept.append(card)
                else:
                    result.unsupported += 1
                    result.rejected.append(
                        Rejected(card, "your notes do not support this", chunk.tag)
                    )
            cards = kept

        added = 0
        for card in cards:
            reason = rejection_reason(card)
            if reason is not None:
                result.low_quality += 1
                result.rejected.append(Rejected(card, reason, chunk.tag))
                continue
            if not deduper.add(card):
                result.duplicates += 1
                result.rejected.append(Rejected(card, "already covered by another card", chunk.tag))
                continue
            card.tags = _tags_for(chunk, shared_tags)
            result.cards.append(card)
            added += 1

        _report(on_chunk, chunk, added)

    return result


def _report(on_chunk: Callable[[Chunk, int], None] | None, chunk: Chunk, added: int) -> None:
    if on_chunk is not None:
        on_chunk(chunk, added)


def _tags_for(chunk: Chunk, extra: list[str]) -> list[str]:
    tags = list(extra)
    if chunk.tag:
        tags.append(chunk.tag)
    return [clean_tag(tag) for tag in tags if tag.strip()]


def clean_tag(tag: str) -> str:
    """Make a tag safe for Anki, where whitespace separates one tag from the next."""
    return "_".join(tag.split())
