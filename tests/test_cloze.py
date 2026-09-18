import sqlite3
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from notetaker.chunking import chunk_markdown
from notetaker.cli import app
from notetaker.export import write_apkg, write_tsv
from notetaker.export.apkg import CLOZE_MODEL_ID, MODEL_ID
from notetaker.generate import generate_cards
from notetaker.llm import FakeLLM
from notetaker.models import Card, CardType
from notetaker.quality import rejection_reason
from notetaker.styles import CLOZE, STYLES

runner = CliRunner()

SENTENCE = "Glycolysis takes place in the {{c1::cytoplasm}}."


def cloze(text: str, extra: str = "") -> Card:
    return Card(question=text, answer=extra, card_type=CardType.CLOZE)


# --- the model ---------------------------------------------------------------


def test_a_cloze_card_needs_a_deletion() -> None:
    with pytest.raises(ValidationError, match="deletion"):
        cloze("Glycolysis takes place in the cytoplasm.")


def test_a_cloze_card_does_not_need_an_answer() -> None:
    assert cloze(SENTENCE).answer == ""


def test_a_basic_card_still_needs_an_answer() -> None:
    with pytest.raises(ValidationError, match="needs an answer"):
        Card(question="What is ATP?", answer="")


def test_deletions_are_listed_in_order() -> None:
    card = cloze("Water moves from {{c1::lower}} to {{c2::higher}} concentration.")
    assert card.deletions == ["lower", "higher"]


def test_the_markup_can_be_stripped_back_out() -> None:
    assert cloze(SENTENCE).without_deletions() == "Glycolysis takes place in the cytoplasm."


def test_a_hint_is_accepted() -> None:
    assert cloze("It occurs in the {{c1::cytoplasm::where}}.").deletions == ["cytoplasm"]


# --- quality rules -----------------------------------------------------------


def test_a_cloze_hiding_the_whole_sentence_is_rejected() -> None:
    card = cloze("{{c1::Glycolysis takes place in the cytoplasm}}")
    assert rejection_reason(card) == "cloze hides the whole sentence"


def test_an_overlong_deletion_is_rejected() -> None:
    card = cloze("The rule is that {{c1::" + "word " * 9 + "}} and that is it.")
    assert rejection_reason(card) == "deletion too long"


def test_a_good_cloze_is_kept() -> None:
    assert rejection_reason(cloze(SENTENCE)) is None


def test_yes_no_rules_do_not_apply_to_cloze() -> None:
    # "Is" would trip the basic yes/no rule; a cloze sentence may start with it.
    assert rejection_reason(cloze("Is is a verb in {{c1::English}} grammar today.")) is None


# --- style plumbing ----------------------------------------------------------


def test_the_cloze_style_asks_for_a_cloze_schema() -> None:
    assert "ClozeDraft" in CLOZE.batch.model_json_schema()["$defs"]


def test_drafts_without_a_deletion_are_dropped_not_fatal() -> None:
    class Stub:
        name = "stub"

        def complete(self, system, user, schema):
            return {"cards": [{"text": "no deletion here"}, {"text": SENTENCE}]}

    result = generate_cards(chunk_markdown("# Bio\n\ntext\n"), Stub(), style=CLOZE)
    assert len(result.cards) == 1
    assert result.low_quality == 1


def test_the_fake_backend_produces_cloze_when_asked() -> None:
    notes = "# Bio\n\nOsmosis is the diffusion of water across a membrane.\n"
    result = generate_cards(chunk_markdown(notes), FakeLLM(), style=CLOZE)
    assert result.cards
    card = result.cards[0]
    assert card.card_type is CardType.CLOZE
    assert card.deletions == ["Osmosis"]


def test_an_unknown_style_is_rejected(tmp_path: Path) -> None:
    notes = tmp_path / "n.md"
    notes.write_text("# A\n\nOsmosis is diffusion of water.\n", encoding="utf-8")
    result = runner.invoke(app, ["cards", str(notes), "--llm", "fake", "--style", "reversed"])
    assert result.exit_code != 0
    assert "unknown style" in result.output


def test_every_registered_style_is_reachable_by_name() -> None:
    assert set(STYLES) == {"basic", "cloze"}


# --- export ------------------------------------------------------------------


def test_the_tsv_declares_the_cloze_note_type(tmp_path: Path) -> None:
    path = write_tsv([cloze(SENTENCE)], tmp_path / "deck.tsv")
    assert "#notetype:Cloze" in path.read_text(encoding="utf-8")


def test_the_tsv_declares_basic_for_basic_cards(tmp_path: Path) -> None:
    path = write_tsv([Card(question="q", answer="a")], tmp_path / "deck.tsv")
    assert "#notetype:Basic" in path.read_text(encoding="utf-8")


def note_model_ids(path: Path, tmp_path: Path) -> list[int]:
    target = tmp_path / "extracted"
    with zipfile.ZipFile(path) as archive:
        archive.extract("collection.anki2", target)
    connection = sqlite3.connect(target / "collection.anki2")
    try:
        return [row[0] for row in connection.execute("select mid from notes").fetchall()]
    finally:
        connection.close()


def test_cloze_cards_use_the_cloze_note_type_in_the_package(tmp_path: Path) -> None:
    path = write_apkg([cloze(SENTENCE)], tmp_path / "deck.apkg", "Bio")
    assert note_model_ids(path, tmp_path) == [CLOZE_MODEL_ID]


def test_basic_cards_use_the_basic_note_type_in_the_package(tmp_path: Path) -> None:
    path = write_apkg([Card(question="q", answer="a")], tmp_path / "deck.apkg", "Bio")
    assert note_model_ids(path, tmp_path) == [MODEL_ID]


def test_the_cli_writes_a_cloze_deck(tmp_path: Path) -> None:
    notes = tmp_path / "bio.md"
    notes.write_text("# Bio\n\nOsmosis is the diffusion of water.\n", encoding="utf-8")
    out = tmp_path / "out"

    result = runner.invoke(
        app, ["cards", str(notes), "--llm", "fake", "--style", "cloze", "--out", str(out)]
    )

    assert result.exit_code == 0
    assert "style     cloze" in result.output
    assert "{{c1::" in (out / "bio.tsv").read_text(encoding="utf-8")


def test_a_cloze_that_reveals_its_own_answer_is_rejected() -> None:
    # Real output: the model restated the topic and then hid it.
    card = cloze("Osmosis: the movement of water from low to high, involving {{c1::osmosis}}.")
    assert rejection_reason(card) == "answer visible in the sentence"


def test_a_multi_word_deletion_visible_elsewhere_is_rejected() -> None:
    card = cloze("Active transport needs energy, and {{c1::active transport}} uses ATP.")
    assert rejection_reason(card) == "answer visible in the sentence"


def test_a_sentence_cut_off_mid_clause_is_rejected() -> None:
    # Real output: the model stopped after "that".
    card = cloze("The Krebs cycle is a series of reactions in the {{c1::matrix}} that")
    assert rejection_reason(card) == "sentence is cut off"


def test_a_sentence_ending_on_the_deletion_is_kept() -> None:
    assert rejection_reason(cloze("Glycolysis takes place in the {{c1::cytoplasm}}")) is None


def test_distinct_nearby_words_are_not_treated_as_revealed() -> None:
    card = cloze("Water moves from {{c1::lower}} to higher solute concentration.")
    assert rejection_reason(card) is None
