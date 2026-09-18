"""Rejecting cards that are not worth studying.

The system prompt asks for atomic, non-guessable cards. Small models agree and
then do it anyway: a 3B model asked explicitly for no yes/no questions, with a
worked example, still produced four of them in a four-section document.
Negative instructions are weak, so the rules are enforced here instead, where
they are deterministic and testable.

A yes/no card is worth catching because it is worse than useless. The student
gets it right half the time by guessing, so the scheduler keeps showing it
while teaching nothing. The cloze equivalent is a sentence with everything
hidden, which gives the student no cue at all.
"""

from __future__ import annotations

import re

from notetaker.models import CLOZE_RE, Card, CardType

AUXILIARY_RE = re.compile(
    r"^(is|are|was|were|do|does|did|can|could|will|would|shall|should|has|have|had|may|might)\b",
    re.IGNORECASE,
)
FOLLOW_UP_RE = re.compile(r"\bif so\b|\bif not\b", re.IGNORECASE)
BOOLEAN_ANSWER_RE = re.compile(r"^(yes|no|true|false|correct|incorrect)\b", re.IGNORECASE)
META_RE = re.compile(
    r"\b(this (section|document|passage|text|handout|lecture|slide|chapter|course)"
    r"|the (notes|passage|handout|lecture|slides?))\b",
    re.IGNORECASE,
)
NON_ANSWER_RE = re.compile(
    r"^(unknown|unclear|n/?a|none|no answer"
    r"|not (specified|stated|mentioned|given|provided|available|clear))\b",
    re.IGNORECASE,
)
"""Answers meaning the model had nothing. They arrive looking like real cards."""

PUNCTUATION_RE = re.compile(r"[^\w\s]")

_FUNCTION_WORD_TEXT = (
    "a an the and or but of in on at to for from by as with is are was were be "
    "been this that these those how why what when where which who it its not"
)
FUNCTION_WORDS = frozenset(_FUNCTION_WORD_TEXT.split())
"""A one-word answer drawn from this set is a truncation, not a fact.

Real notes produced "What is the main focus of biochemical genetics? -> how".
Short answers are otherwise fine -- "Two", "ATP" and "X" are all good cards --
so the rule turns on the word itself, not the length.
"""

_DANGLING_TEXT = (
    "that which and or but of the a an in on to for with from by as at is are "
    "when where while into onto than then"
)
DANGLING_WORDS = frozenset(_DANGLING_TEXT.split())
"""Words a sentence does not end on. A cloze ending here was cut off."""

MAX_ANSWER_WORDS = 40
MIN_REVEALING_LENGTH = 4
"""Shorter than this, a shared word is coincidence rather than a giveaway."""
MAX_DELETION_WORDS = 8
MIN_VISIBLE_WORDS = 3
MAX_SENTENCE_WORDS = 60


def rejection_reason(card: Card) -> str | None:
    """Why this card should be dropped, or None to keep it."""
    if card.card_type is CardType.CLOZE:
        return _cloze_reason(card)
    return _basic_reason(card)


def _basic_reason(card: Card) -> str | None:
    question = card.question.strip()
    answer = card.answer.strip()

    if BOOLEAN_ANSWER_RE.match(answer):
        return "yes/no answer"
    if NON_ANSWER_RE.match(answer) or _is_a_stray_word(answer):
        return "no real answer"
    if _answer_sits_in_the_question(question, answer):
        return "answer is in the question"
    if AUXILIARY_RE.match(question):
        return "yes/no question"
    if FOLLOW_UP_RE.search(question):
        return "compound question"
    if META_RE.search(question):
        return "question about the document"
    if len(answer.split()) > MAX_ANSWER_WORDS:
        return "answer too long"
    return None


def _reveals_its_own_answer(card: Card, visible: list[str]) -> bool:
    """True when a hidden term is also sitting in plain sight in the same sentence.

    Models restating the topic produce these: "Osmosis: the movement of water
    ... involving {{c1::osmosis}}". The student reads the answer off the card.
    """
    shown = {word.strip(".,;:!?()").lower() for word in visible}
    return any(
        all(part.strip(".,;:!?()").lower() in shown for part in deletion.split())
        for deletion in card.deletions
        if deletion.strip()
    )


def _is_a_stray_word(answer: str) -> bool:
    """A lone function word left behind when the model's answer was cut short."""
    words = _normalize(answer).split()
    return len(words) == 1 and words[0] in FUNCTION_WORDS


def _answer_sits_in_the_question(question: str, answer: str) -> bool:
    """Catch a card that gives itself away.

    "Which movement of the 1900s was based on eugenics? -> Eugenics" is a real
    card from a real run. The cloze rules have guarded against this from the
    start; basic cards were simply missed.
    """
    normalized_answer = _normalize(answer)
    if len(normalized_answer) < MIN_REVEALING_LENGTH:
        return False
    return normalized_answer in _normalize(question)


def _normalize(text: str) -> str:
    return " ".join(PUNCTUATION_RE.sub(" ", text.lower()).split())


def _cloze_reason(card: Card) -> str | None:
    text = card.question.strip()

    if META_RE.search(text):
        return "question about the document"

    visible = CLOZE_RE.sub(" ", text).split()
    if len(visible) < MIN_VISIBLE_WORDS:
        return "cloze hides the whole sentence"

    if any(len(deletion.split()) > MAX_DELETION_WORDS for deletion in card.deletions):
        return "deletion too long"

    if _reveals_its_own_answer(card, visible):
        return "answer visible in the sentence"

    # Checked against the filled-in sentence: a cloze may legitimately end on
    # its own deletion, which would otherwise look like it ends on "the".
    filled = card.without_deletions().split()
    if filled and filled[-1].strip(".,;:!?").lower() in DANGLING_WORDS:
        return "sentence is cut off"

    if len(card.without_deletions().split()) > MAX_SENTENCE_WORDS:
        return "sentence too long"

    return None
