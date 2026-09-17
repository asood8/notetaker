"""Prompt construction.

The notes are wrapped in explicit delimiters so that backends can find them
again -- `FakeLLM` relies on this, and it also makes prompt-injection style
confusion between instructions and note content less likely.
"""

from __future__ import annotations

from notetaker.chunking import Chunk

NOTES_OPEN = "<notes>"
NOTES_CLOSE = "</notes>"

SYSTEM = """\
You write flashcards for spaced repetition study.

Rules:
- One fact per card. If a card would need a list as its answer, split it up.
- The question must stand alone. A student seeing it out of context, weeks
  later, should understand what is being asked.
- Never write meta-questions about the document itself, such as "What does
  this section cover?" or "What is listed in the notes?".
- Answers are short: a phrase or a single sentence, not a paragraph.
- Use only what the notes state. Do not add outside knowledge.
- If a passage contains nothing worth memorizing, return no cards for it.\
"""

USER_TEMPLATE = """\
Write up to {max_cards} flashcards from the notes below.

{open}
{text}
{close}\
"""


def build_prompt(chunk: Chunk, max_cards: int) -> tuple[str, str]:
    """Return the `(system, user)` pair for one chunk."""
    user = USER_TEMPLATE.format(
        max_cards=max_cards,
        open=NOTES_OPEN,
        text=chunk.text,
        close=NOTES_CLOSE,
    )
    return SYSTEM, user


def extract_notes(user: str) -> str:
    """Pull the note text back out of a built prompt."""
    start = user.find(NOTES_OPEN)
    end = user.find(NOTES_CLOSE)
    if start == -1 or end == -1:
        return ""
    return user[start + len(NOTES_OPEN) : end].strip()
