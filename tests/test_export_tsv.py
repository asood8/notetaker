from pathlib import Path

from notetaker.export import write_tsv
from notetaker.models import Card


def read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_import_directives_come_first(tmp_path: Path) -> None:
    path = write_tsv([Card(question="q", answer="a")], tmp_path / "deck.tsv")
    assert read(path)[:4] == ["#separator:tab", "#html:true", "#notetype:Basic", "#tags column:3"]


def test_a_card_is_three_tab_separated_fields(tmp_path: Path) -> None:
    card = Card(question="What is ATP?", answer="Adenosine triphosphate", tags=["bio", "ch3"])
    path = write_tsv([card], tmp_path / "deck.tsv")
    assert read(path)[4].split("\t") == ["What is ATP?", "Adenosine triphosphate", "bio ch3"]


def test_newlines_become_breaks_so_rows_are_not_split(tmp_path: Path) -> None:
    card = Card(question="Steps?", answer="one\ntwo\r\nthree")
    path = write_tsv([card], tmp_path / "deck.tsv")
    lines = read(path)
    assert len(lines) == 5
    assert lines[4].split("\t")[1] == "one<br>two<br>three"


def test_tabs_inside_a_field_do_not_create_extra_columns(tmp_path: Path) -> None:
    path = write_tsv([Card(question="a\tb", answer="c\td")], tmp_path / "deck.tsv")
    assert len(read(path)[4].split("\t")) == 3


def test_the_output_directory_is_created(tmp_path: Path) -> None:
    path = write_tsv([Card(question="q", answer="a")], tmp_path / "deep" / "nested" / "deck.tsv")
    assert path.exists()
