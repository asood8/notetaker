"""Drive chunks through a model and collect validated cards."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from pydantic import ValidationError

from notetaker.chunking import Chunk
from notetaker.dedup import Deduper
from notetaker.llm.base import LLMClient, LLMError
from notetaker.models import Card, CardBatch
from notetaker.prompts import build_prompt

DEFAULT_MAX_CARDS_PER_CHUNK = 8


@dataclass
class GenerationResult:
    """Cards, plus what went wrong along the way."""

    cards: list[Card] = field(default_factory=list)
    duplicates: int = 0
    invalid_responses: int = 0
    failed_chunks: int = 0


def generate_cards(
    chunks: Iterable[Chunk],
    client: LLMClient,
    *,
    max_cards_per_chunk: int = DEFAULT_MAX_CARDS_PER_CHUNK,
    extra_tags: Iterable[str] = (),
    on_chunk: Callable[[Chunk, int], None] | None = None,
) -> GenerationResult:
    """Generate cards for every chunk, skipping anything the model gets wrong.

    A bad response for one chunk should never lose the cards from the others,
    so failures are counted and reported rather than raised.
    """
    result = GenerationResult()
    deduper = Deduper()
    shared_tags = list(extra_tags)

    for chunk in chunks:
        system, user = build_prompt(chunk, max_cards_per_chunk)

        try:
            raw = client.complete(system, user, CardBatch.model_json_schema())
        except LLMError:
            result.failed_chunks += 1
            if on_chunk is not None:
                on_chunk(chunk, 0)
            continue

        try:
            batch = CardBatch.model_validate(raw)
        except ValidationError:
            result.invalid_responses += 1
            if on_chunk is not None:
                on_chunk(chunk, 0)
            continue

        added = 0
        for card in batch.cards[:max_cards_per_chunk]:
            if not deduper.add(card):
                result.duplicates += 1
                continue
            card.tags = _tags_for(chunk, shared_tags)
            result.cards.append(card)
            added += 1

        if on_chunk is not None:
            on_chunk(chunk, added)

    return result


def _tags_for(chunk: Chunk, extra: list[str]) -> list[str]:
    tags = list(extra)
    if chunk.tag:
        tags.append(chunk.tag)
    return [clean_tag(tag) for tag in tags if tag.strip()]


def clean_tag(tag: str) -> str:
    """Make a tag safe for Anki, where whitespace separates one tag from the next."""
    return "_".join(tag.split())
