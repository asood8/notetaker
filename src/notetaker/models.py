"""Data models shared across the pipeline.

There are two layers here on purpose. `Card` is what the rest of the program
works with. The `*Draft` models are the shapes the model is asked to fill in,
and they carry only the fields the model should decide -- tags and card type
are ours to set, so they stay out of the JSON schema the model sees.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

CLOZE_RE = re.compile(r"\{\{c(\d+)::(.+?)(?:::(.+?))?\}\}")
"""Anki's cloze syntax: `{{c1::hidden text}}`, optionally `{{c1::text::hint}}`."""


class CardType(StrEnum):
    BASIC = "basic"
    CLOZE = "cloze"


class Card(BaseModel):
    """A finished flashcard.

    For a basic card, `question` and `answer` are the two sides. For a cloze
    card, `question` holds the sentence with its `{{c1::...}}` deletions and
    `answer` is optional extra shown underneath.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(default="", max_length=2000)
    card_type: CardType = CardType.BASIC
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_shape(self) -> Card:
        if self.card_type is CardType.BASIC and not self.answer.strip():
            raise ValueError("a basic card needs an answer")
        if self.card_type is CardType.CLOZE and not CLOZE_RE.search(self.question):
            raise ValueError("a cloze card needs at least one {{c1::...}} deletion")
        return self

    @property
    def deletions(self) -> list[str]:
        """The hidden spans of a cloze card, in the order they appear."""
        return [match.group(2) for match in CLOZE_RE.finditer(self.question)]

    def without_deletions(self) -> str:
        """The cloze sentence with the `{{c1::...}}` markup removed."""
        return CLOZE_RE.sub(lambda match: match.group(2), self.question)


class BasicDraft(BaseModel):
    """One question-and-answer card, as the model returns it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=2000)


class ClozeDraft(BaseModel):
    """One fill-in-the-blank sentence, as the model returns it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=1000)
    extra: str = Field(default="", max_length=2000)


class BasicBatch(BaseModel):
    """`cards` is required on purpose.

    Some models answer with a bare `{}`. With a default this validated as "zero
    cards" and the run reported success while producing nothing at all, which
    is the worst possible failure: silent. Requiring the key turns that into a
    counted invalid response.
    """

    cards: list[BasicDraft]


class ClozeBatch(BaseModel):
    """`cards` is required, for the reason given on `BasicBatch`."""

    cards: list[ClozeDraft]
