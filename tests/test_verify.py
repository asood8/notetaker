"""Reading cards back against the passage they came from."""

from __future__ import annotations

from typing import Any

from notetaker.chunking import Chunk, chunk_markdown
from notetaker.generate import generate_cards
from notetaker.llm.base import LLMError
from notetaker.models import Card
from notetaker.verify import build_check_prompt, check_cards

PASSAGE = "Glycolysis takes place in the cytoplasm and yields two ATP."

CARDS = [
    Card(question="Where does glycolysis occur?", answer="The cytoplasm"),
    Card(question="Which chromosome determines male characteristics?", answer="X"),
]


class Checker:
    """Returns canned verdicts, and remembers what it was asked."""

    name = "checker"

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.prompts.append(user)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def verdicts(*pairs: tuple[int, bool]) -> dict[str, Any]:
    return {"verdicts": [{"index": i, "supported": ok, "quote": ""} for i, ok in pairs]}


# --- the prompt --------------------------------------------------------------


def test_the_passage_and_every_card_are_in_the_prompt() -> None:
    _, user = build_check_prompt(PASSAGE, CARDS)
    assert PASSAGE in user
    assert "1. Q: Where does glycolysis occur?" in user
    assert "2. Q: Which chromosome determines male characteristics?" in user


def test_the_instructions_forbid_outside_knowledge() -> None:
    system, _ = build_check_prompt(PASSAGE, CARDS)
    assert "Do not use anything you know from elsewhere" in system


# --- verdicts ----------------------------------------------------------------


def test_an_unsupported_card_is_rejected() -> None:
    client = Checker(verdicts((1, True), (2, False)))
    assert check_cards(CARDS, PASSAGE, client) == [True, False]


def test_supported_cards_are_kept() -> None:
    client = Checker(verdicts((1, True), (2, True)))
    assert check_cards(CARDS, PASSAGE, client) == [True, True]


def test_a_card_the_checker_ignores_is_kept() -> None:
    # Silence is not evidence against a card.
    client = Checker(verdicts((1, False)))
    assert check_cards(CARDS, PASSAGE, client) == [False, True]


def test_no_cards_means_no_call() -> None:
    client = Checker(verdicts())
    assert check_cards([], PASSAGE, client) == []
    assert client.prompts == []


# --- failing open ------------------------------------------------------------


def test_a_backend_failure_keeps_every_card() -> None:
    # A checker that cannot answer must not be allowed to empty a deck.
    client = Checker(LLMError("ollama is down"))
    assert check_cards(CARDS, PASSAGE, client) == [True, True]


def test_an_unusable_reply_keeps_every_card() -> None:
    client = Checker({"nonsense": True})
    assert check_cards(CARDS, PASSAGE, client) == [True, True]


def test_an_out_of_range_index_does_not_remove_a_card() -> None:
    client = Checker(verdicts((7, False)))
    assert check_cards(CARDS, PASSAGE, client) == [True, True]


# --- through generation ------------------------------------------------------


class Generator:
    """Writes two cards, then judges the second one unsupported."""

    name = "stub"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if "You check whether flashcards" in system:
            return verdicts((1, True), (2, False))
        return {
            "cards": [
                {"question": "Where does glycolysis occur?", "answer": "The cytoplasm"},
                {"question": "Which chromosome makes males?", "answer": "X"},
            ]
        }


def test_unsupported_cards_are_dropped_and_counted() -> None:
    client = Generator()
    chunks = chunk_markdown("# Bio\n\n" + PASSAGE + "\n")

    result = generate_cards(
        chunks,
        client,
        check=lambda cards, passage: check_cards(cards, passage, client),
    )

    assert [card.question for card in result.cards] == ["Where does glycolysis occur?"]
    assert result.unsupported == 1


def test_without_the_checker_nothing_is_verified() -> None:
    client = Generator()
    result = generate_cards(chunk_markdown("# Bio\n\n" + PASSAGE + "\n"), client)
    assert len(result.cards) == 2
    assert result.unsupported == 0


def test_the_checker_sees_the_section_the_cards_came_from() -> None:
    client = Checker(verdicts((1, True)))
    chunk = Chunk(text=PASSAGE, heading_path=("Bio",))
    check_cards(CARDS[:1], chunk.text, client)
    assert PASSAGE in client.prompts[0]
