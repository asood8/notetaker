import sqlite3
import zipfile
from pathlib import Path

from notetaker.export import write_apkg
from notetaker.export.apkg import stable_id
from notetaker.models import Card

FIELD_SEPARATOR = "\x1f"

CARDS = [
    Card(question="What is ATP?", answer="Adenosine triphosphate", tags=["bio", "ch3"]),
    Card(question="Where does glycolysis occur?", answer="The cytoplasm", tags=["bio"]),
]


def notes_in(path: Path, tmp_path: Path) -> list[tuple[str, str, str]]:
    """Read the notes table straight out of the packaged collection."""
    target = tmp_path / "extracted"
    with zipfile.ZipFile(path) as archive:
        archive.extract("collection.anki2", target)

    connection = sqlite3.connect(target / "collection.anki2")
    try:
        rows = connection.execute("select guid, flds, tags from notes order by flds").fetchall()
    finally:
        connection.close()
    return rows


def test_the_package_is_a_zip_containing_a_collection(tmp_path: Path) -> None:
    path = write_apkg(CARDS, tmp_path / "deck.apkg", "Bio")
    with zipfile.ZipFile(path) as archive:
        assert "collection.anki2" in archive.namelist()


def test_every_card_becomes_a_note(tmp_path: Path) -> None:
    path = write_apkg(CARDS, tmp_path / "deck.apkg", "Bio")
    assert len(notes_in(path, tmp_path)) == 2


def test_question_and_answer_land_in_the_right_fields(tmp_path: Path) -> None:
    path = write_apkg(CARDS, tmp_path / "deck.apkg", "Bio")
    fields = {
        row[1].split(FIELD_SEPARATOR)[0]: row[1].split(FIELD_SEPARATOR)[1]
        for row in notes_in(path, tmp_path)
    }
    assert fields["What is ATP?"] == "Adenosine triphosphate"
    assert fields["Where does glycolysis occur?"] == "The cytoplasm"


def test_tags_are_preserved(tmp_path: Path) -> None:
    path = write_apkg(CARDS, tmp_path / "deck.apkg", "Bio")
    tags = {row[1].split(FIELD_SEPARATOR)[0]: row[2].split() for row in notes_in(path, tmp_path)}
    assert tags["What is ATP?"] == ["bio", "ch3"]


def test_the_same_question_keeps_the_same_guid_across_runs(tmp_path: Path) -> None:
    first = write_apkg(CARDS, tmp_path / "a.apkg", "Bio")
    second = write_apkg(CARDS, tmp_path / "b.apkg", "Bio")
    assert [row[0] for row in notes_in(first, tmp_path / "one")] == [
        row[0] for row in notes_in(second, tmp_path / "two")
    ]


def test_editing_an_answer_keeps_the_guid_so_anki_updates_the_card(tmp_path: Path) -> None:
    original = write_apkg(
        [Card(question="What is ATP?", answer="Adenosine triphosphate")],
        tmp_path / "a.apkg",
        "Bio",
    )
    revised = write_apkg(
        [Card(question="What is ATP?", answer="The energy currency of the cell")],
        tmp_path / "b.apkg",
        "Bio",
    )
    assert notes_in(original, tmp_path / "one")[0][0] == notes_in(revised, tmp_path / "two")[0][0]


def test_a_different_question_gets_a_different_guid(tmp_path: Path) -> None:
    path = write_apkg(CARDS, tmp_path / "deck.apkg", "Bio")
    guids = [row[0] for row in notes_in(path, tmp_path)]
    assert len(set(guids)) == 2


def test_deck_ids_are_stable_and_name_dependent() -> None:
    assert stable_id("Bio::Ch3") == stable_id("Bio::Ch3")
    assert stable_id("Bio::Ch3") != stable_id("Bio::Ch4")


def test_deck_ids_fit_in_ankis_id_range() -> None:
    for name in ("Bio", "a" * 500, "", "unicode ✓ deck"):
        assert 0 < stable_id(name) < 2**31


def test_the_output_directory_is_created(tmp_path: Path) -> None:
    path = write_apkg(CARDS, tmp_path / "deep" / "nested" / "deck.apkg", "Bio")
    assert path.exists()
