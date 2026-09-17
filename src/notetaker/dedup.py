"""Duplicate detection.

Chunking means the model never sees the whole document, so the same fact often
comes back more than once, phrased differently. Three cases show up:

1. The identical question, from two chunks that overlap in content.
2. The same question with different wording or punctuation.
3. An inverted pair -- "Where are peripheral proteins attached?" / "the surface
   of the membrane" alongside "What is attached to the surface of the
   membrane?" / "peripheral proteins". Both are fine cards on their own, but
   together they are one fact asked twice.

The rules below are deliberately conservative. An earlier version scored
questions with `difflib` and dropped anything above a similarity threshold,
which looked reasonable until it merged "How many NADH are produced during
glycolysis?" with "How many ATP are produced during glycolysis?" -- two
different facts whose questions differ by one short word and whose answers are
both "Two". Keeping a redundant card costs the user a few seconds; silently
dropping a distinct one loses material they meant to study, and they have no
way to notice. So near-misses are kept.
"""

from __future__ import annotations

import re

from notetaker.models import Card

PUNCTUATION_RE = re.compile(r"[^\w\s]")

MIN_INVERSE_LENGTH = 4
"""Below this, an answer is too short for containment to mean anything."""

_STOPWORD_TEXT = (
    "a an the of in on at to for from by with and or as is are was were be "
    "been being do does did what which who whom whose when where why how that "
    "this these those it its"
)
STOPWORDS = frozenset(_STOPWORD_TEXT.split())


class Deduper:
    """Decides whether a card says something already said."""

    def __init__(self) -> None:
        self._seen: list[_Seen] = []

    def add(self, card: Card) -> bool:
        """Record `card` and return True, or return False if it duplicates an earlier one."""
        candidate = _Seen.of(card)

        for seen in self._seen:
            if candidate.question == seen.question:
                return False
            if candidate.is_inverse_of(seen):
                return False
            if candidate.answer == seen.answer and candidate.keywords == seen.keywords:
                return False

        self._seen.append(candidate)
        return True


class _Seen:
    """A card reduced to the forms the rules compare."""

    __slots__ = ("answer", "keywords", "question")

    def __init__(self, question: str, answer: str, keywords: frozenset[str]) -> None:
        self.question = question
        self.answer = answer
        self.keywords = keywords

    @classmethod
    def of(cls, card: Card) -> _Seen:
        question = normalize(card.question)
        return cls(question, normalize(card.answer), keywords(question))

    def is_inverse_of(self, other: _Seen) -> bool:
        """True when two cards are the same fact with question and answer swapped."""
        if len(self.answer) < MIN_INVERSE_LENGTH or len(other.answer) < MIN_INVERSE_LENGTH:
            return False
        return self.answer in other.question and other.answer in self.question


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return " ".join(PUNCTUATION_RE.sub(" ", text.lower()).split())


def keywords(normalized: str) -> frozenset[str]:
    """The content words of a normalized question, ignoring filler and plurals."""
    return frozenset(_stem(word) for word in normalized.split() if word not in STOPWORDS)


def _stem(word: str) -> str:
    """Crude singularization, enough to match `occur` with `occurs`.

    This only ever feeds set comparison, and the rule that uses it also
    requires the two answers to be identical, so over-stemming is harmless.
    """
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word
