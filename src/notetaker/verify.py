"""Checking cards back against the notes they came from.

This answers one question per card: does the passage actually say this? It is
not a fact checker, and it cannot be. Asked whether a card is *true*, a model
is back to reciting its own knowledge, which is exactly what produced the bad
cards. Asked whether a claim appears in a passage sitting in front of it, and
made to quote the words, it is doing something much closer to reading.

That narrower question is still the useful one. The worst card found in real
lecture notes -- "Which sex chromosome determines male characteristics? -> X"
-- came from a near-empty overview slide. The model had nothing to work from
and filled the gap from memory. Nothing in the passage supports it, so this
check is the kind that catches it.

Two consequences worth being clear about:

- If your notes are wrong, a card repeating them faithfully passes. This checks
  fidelity to the source, not truth.
- The check runs on the same model that wrote the cards, so it is fallible too.
  It is a filter that removes obvious inventions, not a guarantee.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field, ValidationError

from notetaker.llm.base import LLMClient, LLMError
from notetaker.models import Card

SYSTEM = """You check whether flashcards are supported by a passage.

You are given a passage and a numbered list of cards. For each card, decide
whether the passage states the answer, or says something that directly implies
it.

Rules:
- Quote the words from the passage that support the card. If you cannot quote
  them, the card is not supported.
- Judge only against the passage. Do not use anything you know from elsewhere.
  A card can be perfectly true and still unsupported here.
- A card that adds detail the passage does not contain is not supported, even
  if the subject matter is the same.
- Return a verdict for every card, using the numbers given."""

USER_TEMPLATE = """Passage:

<passage>
{passage}
</passage>

Cards:

{cards}

Give a verdict for each of the {count} cards."""


class Verdict(BaseModel):
    """One card's result."""

    index: int = Field(ge=1)
    supported: bool
    quote: str = Field(default="", max_length=500)


class VerdictBatch(BaseModel):
    verdicts: list[Verdict]


def build_check_prompt(passage: str, cards: Sequence[Card]) -> tuple[str, str]:
    listed = "\n".join(
        f"{number}. Q: {card.question}\n   A: {card.answer}"
        for number, card in enumerate(cards, start=1)
    )
    user = USER_TEMPLATE.format(passage=passage, cards=listed, count=len(cards))
    return SYSTEM, user


def check_cards(cards: Sequence[Card], passage: str, client: LLMClient) -> list[bool]:
    """Return, for each card, whether the passage supports it.

    Fails open. A checker that cannot answer must not be allowed to throw away
    a deck, so anything it does not clearly reject is kept.
    """
    if not cards:
        return []

    system, user = build_check_prompt(passage, cards)

    try:
        raw = client.complete(system, user, VerdictBatch.model_json_schema())
    except LLMError:
        return [True] * len(cards)

    try:
        batch = VerdictBatch.model_validate(raw)
    except ValidationError:
        return [True] * len(cards)

    # Only an explicit rejection removes a card. A card the model forgot to
    # mention keeps its place, for the same reason the whole function fails
    # open: silence is not evidence against it.
    rejected = {verdict.index for verdict in batch.verdicts if not verdict.supported}
    return [number not in rejected for number in range(1, len(cards) + 1)]
