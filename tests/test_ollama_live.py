"""Checks that need a real Ollama server.

Excluded from the default run and from CI. Use them when changing prompts or
trying a new model:

    pytest -m integration
"""

import pytest

from notetaker.chunking import chunk_markdown
from notetaker.generate import generate_cards
from notetaker.llm import OllamaLLM

pytestmark = pytest.mark.integration

NOTES = """\
# Transport

Osmosis is the diffusion of water across a selectively permeable membrane.
Active transport is movement that requires energy supplied by ATP.
"""


def test_a_local_model_produces_usable_cards() -> None:
    result = generate_cards(chunk_markdown(NOTES), OllamaLLM("llama3.2"), max_cards_per_chunk=4)

    assert result.cards, "the model returned no cards"
    assert result.failed_chunks == 0
    assert all(card.question.strip() for card in result.cards)
    assert all(card.tags == ["Transport"] for card in result.cards)

    joined = " ".join(card.question.lower() + card.answer.lower() for card in result.cards)
    assert "osmosis" in joined or "transport" in joined
