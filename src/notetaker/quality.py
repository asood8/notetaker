"""Rejecting cards that are not worth studying.

The system prompt asks for atomic, non-guessable cards. Small models agree and
then do it anyway: a 3B model asked explicitly for no yes/no questions still
produced four of them in a four-section document. Negative instructions are
weak, so the rule is enforced here instead, where it is deterministic and
testable.

A yes/no card is worth catching because it is worse than useless. The student
gets it right half the time by guessing, so the scheduler keeps showing it
while teaching nothing.
"""

from __future__ import annotations

import re

from notetaker.models import Card

AUXILIARY_RE = re.compile(
    r"^(is|are|was|were|do|does|did|can|could|will|would|shall|should|has|have|had|may|might)\b",
    re.IGNORECASE,
)
FOLLOW_UP_RE = re.compile(r"\bif so\b|\bif not\b", re.IGNORECASE)
BOOLEAN_ANSWER_RE = re.compile(r"^(yes|no|true|false|correct|incorrect)\b", re.IGNORECASE)
META_RE = re.compile(
    r"\b(this (section|document|passage|text)|the notes|the passage)\b",
    re.IGNORECASE,
)

MAX_ANSWER_WORDS = 40


def rejection_reason(card: Card) -> str | None:
    """Why this card should be dropped, or None to keep it."""
    question = card.question.strip()
    answer = card.answer.strip()

    if BOOLEAN_ANSWER_RE.match(answer):
        return "yes/no answer"
    if AUXILIARY_RE.match(question):
        return "yes/no question"
    if FOLLOW_UP_RE.search(question):
        return "compound question"
    if META_RE.search(question):
        return "question about the document"
    if len(answer.split()) > MAX_ANSWER_WORDS:
        return "answer too long"
    return None
