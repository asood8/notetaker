"""Run the same notes through several models and report what comes back.

This is a measuring tool, not a test. Card quality is a judgement call, so it
prints the cards for you to read and counts only the things that can be
counted: how long a model took, whether it honored the schema, and how many
cards tripped one of the obvious quality rules.

    python scripts/compare_models.py --models llama3.2 llama3.1:8b

Results worth keeping go in docs/model-notes.md.
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

from notetaker.chunking import chunk_markdown
from notetaker.generate import generate_cards
from notetaker.llm import OllamaLLM
from notetaker.models import Card
from notetaker.styles import STYLES

DEFAULT_NOTES = Path(__file__).resolve().parent.parent / "examples" / "sample_notes.md"

YES_NO_RE = re.compile(
    r"^(is|are|was|were|do|does|did|can|could|will|would|has|have|had|should)\b",
    re.IGNORECASE,
)
COMPOUND_RE = re.compile(r"\band\b.*\?|\bif so\b", re.IGNORECASE)


def yes_no(card: Card) -> bool:
    """Questions a student can answer by guessing."""
    return bool(YES_NO_RE.match(card.question.strip()))


def compound(card: Card) -> bool:
    """Questions asking two things at once."""
    return bool(COMPOUND_RE.search(card.question))


def wordy(card: Card) -> bool:
    """Answers that are a paragraph rather than a fact."""
    return len(card.answer.split()) > 25


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--notes", type=Path, default=DEFAULT_NOTES)
    parser.add_argument("--max-cards", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--style", choices=sorted(STYLES), default="basic")
    parser.add_argument("--show-cards", action="store_true")
    args = parser.parse_args()

    chunks = chunk_markdown(args.notes.read_text(encoding="utf-8"))
    print(f"{args.notes.name}: {len(chunks)} sections\n")

    rows = []
    for model in args.models:
        print(f"--- {model} ---", flush=True)
        start = time.time()
        result = generate_cards(
            chunks,
            OllamaLLM(model, timeout=args.timeout),
            style=STYLES[args.style],
            max_cards_per_chunk=args.max_cards,
        )
        elapsed = time.time() - start

        flagged = {
            "yes/no": sum(yes_no(card) for card in result.cards),
            "compound": sum(compound(card) for card in result.cards),
            "wordy": sum(wordy(card) for card in result.cards),
        }
        rows.append((model, elapsed, result, flagged))

        print(f"  {elapsed:.0f}s, {len(result.cards)} cards, {result.duplicates} dup dropped")
        print(
            f"  failed sections: {result.failed_chunks}, "
            f"invalid: {result.invalid_responses}, dropped: {result.low_quality}"
        )
        print(f"  flagged: {flagged}")
        if args.show_cards:
            for c in result.cards:
                mark = "!" if (yes_no(c) or compound(c) or wordy(c)) else " "
                print(f"   {mark} {c.question}  ->  {c.answer}")
        print(flush=True)

    print("\n| Model | Time | Cards | Dup | Failed | yes/no | compound | wordy |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for model, elapsed, result, flagged in rows:
        print(
            f"| `{model}` | {elapsed:.0f}s | {len(result.cards)} | {result.duplicates} "
            f"| {result.failed_chunks} | {flagged['yes/no']} | {flagged['compound']} "
            f"| {flagged['wordy']} |"
        )


if __name__ == "__main__":
    main()
