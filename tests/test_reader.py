from pathlib import Path

import pytest
from fpdf import FPDF
from typer.testing import CliRunner

from notetaker.cli import app
from notetaker.reader import UnreadableNotes, clean_extracted, read_notes

runner = CliRunner()


def make_pdf(path: Path, pages: list[str]) -> Path:
    pdf = FPDF()
    pdf.set_font("helvetica", size=12)
    for body in pages:
        pdf.add_page()
        pdf.multi_cell(0, 8, body)
    pdf.output(str(path))
    return path


def test_markdown_is_read_as_text(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("# Bio\n\nOsmosis is diffusion.\n", encoding="utf-8")
    assert "Osmosis" in read_notes(path)


def test_a_txt_file_is_read(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("plain text notes", encoding="utf-8")
    assert read_notes(path) == "plain text notes"


def test_an_unsupported_extension_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "notes.docx"
    path.write_bytes(b"not really a docx")
    with pytest.raises(UnreadableNotes, match="cannot read .docx"):
        read_notes(path)


def test_text_is_extracted_from_a_pdf(tmp_path: Path) -> None:
    path = make_pdf(tmp_path / "notes.pdf", ["Osmosis is the diffusion of water."])
    assert "Osmosis is the diffusion of water." in read_notes(path)


def test_every_page_of_a_pdf_is_read(tmp_path: Path) -> None:
    path = make_pdf(tmp_path / "notes.pdf", ["Page one about glycolysis.", "Page two about ATP."])
    text = read_notes(path)
    assert "glycolysis" in text
    assert "ATP" in text


def test_a_file_that_is_not_a_pdf_is_reported_clearly(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"this is not a pdf at all")
    with pytest.raises(UnreadableNotes, match="not a readable PDF"):
        read_notes(path)


def test_a_pdf_with_no_text_layer_suggests_it_is_a_scan(tmp_path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()  # a page with nothing on it
    path = tmp_path / "scan.pdf"
    pdf.output(str(path))
    with pytest.raises(UnreadableNotes, match="no text layer"):
        read_notes(path)


# --- the cleanup that makes extracted text usable ----------------------------


def test_hyphenated_line_breaks_are_rejoined() -> None:
    assert clean_extracted("mitochon-\ndrial matrix") == "mitochondrial matrix"


def test_hard_wrapped_lines_become_one_sentence() -> None:
    wrapped = "Osmosis is the diffusion\nof water across a\nmembrane."
    assert clean_extracted(wrapped) == "Osmosis is the diffusion of water across a membrane."


def test_paragraph_breaks_are_preserved() -> None:
    assert (
        clean_extracted("First para\nline two\n\nSecond para")
        == "First para line two\n\nSecond para"
    )


def test_trailing_whitespace_does_not_create_empty_blocks() -> None:
    # Prose either side, so the heading heuristic stays out of the way.
    assert clean_extracted("First line.   \n\nSecond line.") == "First line.\n\nSecond line."


def test_empty_input_stays_empty() -> None:
    assert clean_extracted("   \n\n  ") == ""


# --- through the CLI ---------------------------------------------------------


def test_the_cli_generates_cards_from_a_pdf(tmp_path: Path) -> None:
    body = (
        "Osmosis is the diffusion of water across a selectively permeable membrane. "
        "Glycolysis is the breakdown of glucose into pyruvate."
    )
    notes = make_pdf(tmp_path / "bio.pdf", [body])
    out = tmp_path / "out"

    result = runner.invoke(app, ["cards", str(notes), "--llm", "fake", "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert (out / "bio.tsv").exists()
    assert "Osmosis" in (out / "bio.tsv").read_text(encoding="utf-8")


def test_the_cli_reports_an_unreadable_file(tmp_path: Path) -> None:
    notes = tmp_path / "notes.docx"
    notes.write_bytes(b"nope")
    result = runner.invoke(app, ["cards", str(notes), "--llm", "fake"])
    assert result.exit_code == 1
    assert "cannot read" in result.output


# --- recovering headings a PDF only shows visually ---------------------------


def test_a_short_line_above_prose_becomes_a_heading() -> None:
    text = clean_extracted("Transport\n\nPassive transport needs no energy at all.")
    assert text.startswith("## Transport")


def test_consecutive_headings_are_both_kept() -> None:
    text = clean_extracted("Cell Biology\n\nThe Cell Membrane\n\nIt is a bilayer of lipids.")
    assert text.splitlines()[0] == "## Cell Biology"
    assert "## The Cell Membrane" in text


def test_a_short_line_with_nothing_after_it_is_not_a_heading() -> None:
    # A caption or a stray last line heads nothing, so it is prose.
    assert (
        clean_extracted("Some real prose here.\n\nFigure 1") == "Some real prose here.\n\nFigure 1"
    )


def test_a_sentence_is_not_a_heading() -> None:
    text = clean_extracted("This ends in a period.\n\nMore prose follows here.")
    assert "##" not in text


def test_a_bullet_is_not_a_heading() -> None:
    text = clean_extracted("- Integral proteins\n\nThey span the bilayer completely.")
    assert "##" not in text


def test_a_long_line_is_not_a_heading() -> None:
    long_line = "word " * 20
    assert "##" not in clean_extracted(f"{long_line}\n\nFollowed by prose here.")


def test_headings_recovered_from_a_pdf_become_tags(tmp_path: Path) -> None:
    from notetaker.chunking import chunk_markdown

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", "B", 14)
    pdf.multi_cell(0, 8, "Transport")
    pdf.ln(3)
    pdf.set_font("helvetica", "", 11)
    pdf.multi_cell(0, 6, "Passive transport is movement across a membrane without energy.")
    path = tmp_path / "notes.pdf"
    pdf.output(str(path))

    chunks = chunk_markdown(read_notes(path))
    assert [chunk.tag for chunk in chunks] == ["Transport"]
