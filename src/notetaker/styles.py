"""The two kinds of card this tool can produce.

A style bundles everything that differs between them: the instructions, the
JSON shape the model is asked for, and how that shape becomes a `Card`.
Keeping them together means `generate.py` has no idea which style it is
running, and adding a third would not touch it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from notetaker.models import (
    BasicBatch,
    BasicDraft,
    Card,
    CardType,
    ClozeBatch,
    ClozeDraft,
)
from notetaker.prompts import (
    SYSTEM_BASIC,
    SYSTEM_CLOZE,
    USER_TEMPLATE_BASIC,
    USER_TEMPLATE_CLOZE,
)


@dataclass(frozen=True)
class Style:
    """How to ask for a kind of card, and how to read the answer."""

    name: str
    batch: type[BaseModel]
    system: str
    template: str
    to_cards: Callable[[BaseModel], list[Card]]


def _drafts_to_cards(drafts: Sequence[BaseModel], build: Callable[[BaseModel], Card]) -> list[Card]:
    """Convert what the model returned, dropping any card that will not hold up.

    A draft can satisfy the JSON schema and still be unusable -- a cloze
    sentence with no deletion in it, most often -- so each one is validated
    individually rather than failing the whole batch.
    """
    cards = []
    for draft in drafts:
        try:
            cards.append(build(draft))
        except ValidationError:
            continue
    return cards


def _basic_card(draft: BasicDraft) -> Card:
    return Card(question=draft.question, answer=draft.answer, card_type=CardType.BASIC)


def _cloze_card(draft: ClozeDraft) -> Card:
    return Card(question=draft.text, answer=draft.extra, card_type=CardType.CLOZE)


def _basic_to_cards(batch: BaseModel) -> list[Card]:
    assert isinstance(batch, BasicBatch)
    return _drafts_to_cards(batch.cards, _basic_card)


def _cloze_to_cards(batch: BaseModel) -> list[Card]:
    assert isinstance(batch, ClozeBatch)
    return _drafts_to_cards(batch.cards, _cloze_card)


BASIC = Style(
    name="basic",
    batch=BasicBatch,
    system=SYSTEM_BASIC,
    template=USER_TEMPLATE_BASIC,
    to_cards=_basic_to_cards,
)

CLOZE = Style(
    name="cloze",
    batch=ClozeBatch,
    system=SYSTEM_CLOZE,
    template=USER_TEMPLATE_CLOZE,
    to_cards=_cloze_to_cards,
)

STYLES = {style.name: style for style in (BASIC, CLOZE)}
