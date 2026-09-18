"""Prompt construction.

The notes are wrapped in explicit delimiters so that backends can find them
again -- `FakeLLM` relies on this, and it also makes confusion between
instructions and note content less likely.

Cloze examples live in the system prompts rather than the user templates,
because the user templates go through `str.format` and Anki's `{{c1::...}}`
syntax would be eaten by it.
"""

from __future__ import annotations

from notetaker.chunking import Chunk

NOTES_OPEN = "<notes>"
NOTES_CLOSE = "</notes>"

SYSTEM_BASIC = """You write flashcards for spaced repetition study.

Rules:
- One fact per card. If a card would need a list as its answer, split it up.
- The question must stand alone. A student seeing it out of context, weeks
  later, should understand what is being asked.
- Never write a question that can be answered with yes or no. "Does glycolysis
  require oxygen?" is a bad card; "Which stage of respiration does not require
  oxygen?" is a good one.
- Ask one thing per question. No question joining two asks with "and", and no
  follow-ups such as "if so, which?".
- Never write meta-questions about the document itself, such as "What does
  this section cover?" or "What is listed in the notes?".
- Answers are short: a phrase or a single sentence, not a paragraph. Give the
  fact itself, not a sentence restating the question.
- Do not write two cards that state the same fact in reverse.
- Use only what the notes state. Do not add outside knowledge.
- If a passage contains nothing worth memorizing, return no cards for it."""

SYSTEM_CLOZE = """You write fill-in-the-blank flashcards for spaced repetition study.

Each card is one sentence taken from the notes with the key term hidden, using
Anki's cloze syntax. Write {{c1::the hidden text}} around the term to hide.

Good: Glycolysis takes place in the {{c1::cytoplasm}}.
Good: Osmosis moves water from {{c1::lower}} to {{c1::higher}} solute concentration.
Bad:  {{c1::Glycolysis takes place in the cytoplasm}}.
Bad:  Glycolysis takes place in the cytoplasm.

Rules:
- Hide the term worth remembering, not the sentence. Most of the sentence must
  remain visible, or there is nothing left to cue the answer.
- Hide the distinctive term, not the generic word next to it. In "Integral
  proteins span the bilayer", hide "Integral proteins", never just "proteins".
- Hide something specific: a name, a number, a place, a term. Never hide a
  whole clause.
- Copy the sentence from the notes and add only the cloze markers. Do not
  invent trailing phrases such as "involving X" so that there is something to
  hide. If a sentence has nothing worth hiding, skip it.
- Never hide a word that also appears elsewhere in the same sentence. The
  student would simply read the answer off the card.
- Finish the sentence. Never stop mid-clause on a word like "that" or "which".
- The visible part must be enough to identify what is missing. A student
  reading only the visible words should know what kind of thing is hidden.
- Keep each sentence short and self-contained. Do not refer to "the above" or
  "this section".
- Use only what the notes state. Do not add outside knowledge.
- If a passage contains nothing worth memorizing, return no cards for it."""

USER_TEMPLATE_BASIC = """Write up to {max_cards} flashcards from the notes below.

{open}
{text}
{close}"""

USER_TEMPLATE_CLOZE = """Write up to {max_cards} fill-in-the-blank cards from the notes below.

{open}
{text}
{close}"""


def build_prompt(chunk: Chunk, max_cards: int, *, system: str, template: str) -> tuple[str, str]:
    """Return the `(system, user)` pair for one chunk."""
    user = template.format(
        max_cards=max_cards,
        open=NOTES_OPEN,
        text=chunk.text,
        close=NOTES_CLOSE,
    )
    return system, user


def extract_notes(user: str) -> str:
    """Pull the note text back out of a built prompt."""
    start = user.find(NOTES_OPEN)
    end = user.find(NOTES_CLOSE)
    if start == -1 or end == -1:
        return ""
    return user[start + len(NOTES_OPEN) : end].strip()
