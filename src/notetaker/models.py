"""Data models shared across the pipeline."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Card(BaseModel):
    """A single flashcard."""

    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=2000)
    tags: list[str] = Field(default_factory=list)

    def dedup_key(self) -> str:
        """Normalized question text, used to recognize duplicate cards."""
        collapsed = " ".join(self.question.lower().split())
        return collapsed.rstrip("?.! ")


class CardBatch(BaseModel):
    """The shape the model is asked to return for a single chunk."""

    cards: list[Card] = Field(default_factory=list)
