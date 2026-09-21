from typing import Any

import pytest

from notetaker.chunking import Chunk, chunk_markdown
from notetaker.generate import generate_cards
from notetaker.llm import FakeLLM
from notetaker.llm.base import LLMError


class StubLLM:
    """Returns canned payloads, one per call."""

    name = "stub"

    def __init__(self, *payloads: Any) -> None:
        self.payloads = list(payloads)
        self.calls = 0

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        if isinstance(payload, Exception):
            raise payload
        return payload


def chunks(*texts: str) -> list[Chunk]:
    return [Chunk(text=text, heading_path=("Topic",)) for text in texts]


def card(question: str, answer: str = "an answer") -> dict[str, str]:
    return {"question": question, "answer": answer}


def test_cards_are_tagged_with_their_heading_path() -> None:
    client = StubLLM({"cards": [card("What is ATP?")]})
    result = generate_cards(chunks("a"), client)
    assert result.cards[0].tags == ["Topic"]


def test_extra_tags_come_before_the_heading_tag() -> None:
    client = StubLLM({"cards": [card("What is ATP?")]})
    result = generate_cards(chunks("a"), client, extra_tags=["bio101"])
    assert result.cards[0].tags == ["bio101", "Topic"]


def test_duplicate_questions_are_dropped_across_chunks() -> None:
    client = StubLLM({"cards": [card("What is ATP?")]})
    result = generate_cards(chunks("a", "b", "c"), client)
    assert len(result.cards) == 1
    assert result.duplicates == 2


def test_duplicate_detection_ignores_case_spacing_and_punctuation() -> None:
    client = StubLLM(
        {"cards": [card("What is ATP?")]},
        {"cards": [card("what   is  atp")]},
    )
    result = generate_cards(chunks("a", "b"), client)
    assert len(result.cards) == 1
    assert result.duplicates == 1


def test_a_malformed_response_is_counted_and_does_not_stop_the_run() -> None:
    client = StubLLM(
        {"cards": [{"question": "", "answer": ""}]},
        {"cards": [card("What is ATP?")]},
    )
    result = generate_cards(chunks("a", "b"), client)
    assert result.invalid_responses == 1
    assert len(result.cards) == 1


def test_a_backend_failure_is_counted_and_does_not_stop_the_run() -> None:
    client = StubLLM(LLMError("boom"), {"cards": [card("What is ATP?")]})
    result = generate_cards(chunks("a", "b"), client)
    assert result.failed_chunks == 1
    assert len(result.cards) == 1


def test_a_chunk_cannot_exceed_its_card_budget() -> None:
    client = StubLLM({"cards": [card(f"Question {i}?") for i in range(20)]})
    result = generate_cards(chunks("a"), client, max_cards_per_chunk=3)
    assert len(result.cards) == 3


def test_whitespace_around_fields_is_stripped() -> None:
    client = StubLLM({"cards": [{"question": "  What is ATP?  ", "answer": "  energy  "}]})
    result = generate_cards(chunks("a"), client)
    assert result.cards[0].question == "What is ATP?"
    assert result.cards[0].answer == "energy"


def test_the_fake_backend_produces_cards_from_real_notes() -> None:
    notes = "# Bio\n\nOsmosis is the diffusion of water across a membrane.\n"
    result = generate_cards(chunk_markdown(notes), FakeLLM())
    assert result.cards
    assert result.cards[0].question == "What is Osmosis?"
    assert "diffusion of water" in result.cards[0].answer


@pytest.mark.parametrize("payload", [{}, {"cards": "nope"}, {"cards": [{"question": "q"}]}])
def test_responses_that_do_not_match_the_schema_are_rejected(payload: Any) -> None:
    result = generate_cards(chunks("a"), StubLLM(payload))
    assert result.cards == []


def test_a_bare_empty_object_is_an_invalid_response_not_a_silent_zero() -> None:
    # llama3.1:8b answers `{}` to the cloze prompt. When `cards` had a default
    # this validated as "zero cards" and the run claimed success.
    result = generate_cards(chunks("a"), StubLLM({}))
    assert result.cards == []
    assert result.invalid_responses == 1


def test_an_explicitly_empty_card_list_is_accepted() -> None:
    # A model is allowed to say a passage has nothing worth memorizing.
    result = generate_cards(chunks("a"), StubLLM({"cards": []}))
    assert result.cards == []
    assert result.invalid_responses == 0


def test_admin_sections_never_reach_the_model() -> None:
    from notetaker.chunking import Chunk

    client = StubLLM({"cards": [card("When is Exam 1?", "February 19th")]})
    chunks = [
        Chunk(text="Exam 1 is on February 19th.", heading_path=("Logistics",)),
        Chunk(text="Osmosis is the diffusion of water.", heading_path=("Transport",)),
    ]

    result = generate_cards(chunks, client)

    assert client.calls == 1, "the admin section should not have been sent"
    assert result.skipped_sections == 1
