from pathlib import Path

from typer.testing import CliRunner

from notetaker import __version__
from notetaker.cli import app

runner = CliRunner()

NOTES = """\
# Biology

Osmosis is the diffusion of water across a selectively permeable membrane.

Active transport is movement that requires energy supplied by ATP.
"""


def write_notes(tmp_path: Path) -> Path:
    path = tmp_path / "bio.md"
    path.write_text(NOTES, encoding="utf-8")
    return path


def test_version_command_prints_the_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_cards_writes_a_tsv_next_to_the_requested_output_dir(tmp_path: Path) -> None:
    notes = write_notes(tmp_path)
    out = tmp_path / "out"

    result = runner.invoke(app, ["cards", str(notes), "--llm", "fake", "--out", str(out)])

    assert result.exit_code == 0
    written = out / "bio.tsv"
    assert written.exists()
    assert "Osmosis" in written.read_text(encoding="utf-8")


def test_cards_applies_extra_tags(tmp_path: Path) -> None:
    notes = write_notes(tmp_path)
    out = tmp_path / "out"

    result = runner.invoke(
        app, ["cards", str(notes), "--llm", "fake", "--out", str(out), "--tag", "bio101"]
    )

    assert result.exit_code == 0
    assert "bio101" in (out / "bio.tsv").read_text(encoding="utf-8")


def test_cards_fails_clearly_on_an_empty_file(tmp_path: Path) -> None:
    notes = tmp_path / "empty.md"
    notes.write_text("", encoding="utf-8")

    result = runner.invoke(
        app, ["cards", str(notes), "--llm", "fake", "--out", str(tmp_path / "out")]
    )

    assert result.exit_code == 1
    assert "no usable content" in result.output


def test_cards_fails_clearly_on_a_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["cards", str(tmp_path / "nope.md"), "--llm", "fake"])
    assert result.exit_code != 0


def test_an_unknown_backend_is_rejected(tmp_path: Path) -> None:
    notes = write_notes(tmp_path)
    result = runner.invoke(app, ["cards", str(notes), "--llm", "gpt9"])
    assert result.exit_code != 0
    assert "unknown backend" in result.output


def test_progress_is_reported_per_section(tmp_path: Path) -> None:
    notes = write_notes(tmp_path)
    result = runner.invoke(
        app, ["cards", str(notes), "--llm", "fake", "--out", str(tmp_path / "out")]
    )
    assert result.exit_code == 0
    assert "[1/1]" in result.output


def test_cards_writes_both_an_apkg_and_a_tsv(tmp_path: Path) -> None:
    notes = write_notes(tmp_path)
    out = tmp_path / "out"

    result = runner.invoke(
        app, ["cards", str(notes), "--llm", "fake", "--out", str(out), "--deck", "Bio::Ch1"]
    )

    assert result.exit_code == 0
    assert (out / "bio.apkg").exists()
    assert (out / "bio.tsv").exists()


def test_tags_with_spaces_are_made_safe_for_anki(tmp_path: Path) -> None:
    notes = write_notes(tmp_path)
    out = tmp_path / "out"

    result = runner.invoke(
        app,
        ["cards", str(notes), "--llm", "fake", "--out", str(out), "--tag", "bio 101"],
    )

    assert result.exit_code == 0
    tags = (out / "bio.tsv").read_text(encoding="utf-8").splitlines()[4].split("\t")[2]
    assert "bio_101" in tags


def test_a_reasoning_model_is_warned_about(tmp_path: Path, monkeypatch) -> None:
    notes = write_notes(tmp_path)
    # The run itself never happens: the warning is printed before any request.
    result = runner.invoke(
        app,
        ["cards", str(notes), "--model", "qwen3.5:9b", "--timeout", "0.01"],
    )
    assert "reasons before answering" in result.output


def test_no_warning_for_a_plain_model(tmp_path: Path) -> None:
    notes = write_notes(tmp_path)
    result = runner.invoke(
        app, ["cards", str(notes), "--llm", "fake", "--out", str(tmp_path / "out")]
    )
    assert "reasons before answering" not in result.output
