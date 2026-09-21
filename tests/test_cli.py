from pathlib import Path

import pytest
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


# --- looking at a file before committing to a run ----------------------------


def test_inspect_lists_each_section_with_its_tag(tmp_path: Path) -> None:
    notes = tmp_path / "bio.md"
    notes.write_text(
        "# Biology\n\n## Transport\n\nOsmosis moves water.\n\n## Glycolysis\n\nIt makes ATP.\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["inspect", str(notes)])

    assert result.exit_code == 0
    assert "Biology::Transport" in result.output
    assert "Biology::Glycolysis" in result.output
    assert "2 sections" in result.output


def test_inspect_estimates_how_long_a_run_will_take(tmp_path: Path) -> None:
    notes = write_notes(tmp_path)
    result = runner.invoke(app, ["inspect", str(notes)])
    assert "estimate" in result.output


def test_inspect_warns_about_sections_with_no_heading(tmp_path: Path) -> None:
    notes = tmp_path / "loose.md"
    notes.write_text("Osmosis is the diffusion of water across a membrane.\n", encoding="utf-8")

    result = runner.invoke(app, ["inspect", str(notes)])

    assert "untagged" in result.output
    assert "--tag" in result.output


def test_inspect_truncates_a_very_long_list(tmp_path: Path) -> None:
    notes = tmp_path / "big.md"
    body = "".join(f"## Section {n}\n\nSome content about topic {n}.\n\n" for n in range(45))
    notes.write_text(body, encoding="utf-8")

    result = runner.invoke(app, ["inspect", str(notes)])

    assert "and 15 more" in result.output


def test_inspect_never_calls_a_model(tmp_path: Path) -> None:
    # No --llm option exists on inspect at all; it is a read-only look at the file.
    notes = write_notes(tmp_path)
    result = runner.invoke(app, ["inspect", str(notes), "--chunk-chars", "100"])
    assert result.exit_code == 0


def test_inspect_reports_an_empty_file(tmp_path: Path) -> None:
    notes = tmp_path / "empty.md"
    notes.write_text("   \n", encoding="utf-8")
    result = runner.invoke(app, ["inspect", str(notes)])
    assert result.exit_code == 1


def long_notes(tmp_path: Path, count: int = 6) -> Path:
    notes = tmp_path / "big.md"
    topics = ["osmosis", "glycolysis", "mitosis", "telomeres", "enzymes", "ribosomes"]
    notes.write_text(
        "".join(
            f"## Section {n}\n\n"
            f"{topics[n % len(topics)].title()} is a process that governs transport in cells.\n\n"
            for n in range(count)
        ),
        encoding="utf-8",
    )
    return notes


def run_sections(tmp_path: Path, spec: str, count: int = 6):
    notes = long_notes(tmp_path, count)
    return runner.invoke(
        app,
        ["cards", str(notes), "--llm", "fake", "--sections", spec, "--out", str(tmp_path / "out")],
    )


def test_a_leading_range_takes_the_first_sections(tmp_path: Path) -> None:
    result = run_sections(tmp_path, "-2")
    assert result.exit_code == 0, result.output
    assert "sections  1-2 of 6" in result.output
    assert "[2/2]" in result.output
    assert "[3/" not in result.output


def test_a_middle_range_skips_what_came_before(tmp_path: Path) -> None:
    result = run_sections(tmp_path, "3-4")
    assert result.exit_code == 0, result.output
    assert "sections  3-4 of 6" in result.output
    assert "[2/2]" in result.output


def test_an_open_ended_range_runs_to_the_end(tmp_path: Path) -> None:
    result = run_sections(tmp_path, "5-")
    assert result.exit_code == 0, result.output
    assert "sections  5-6 of 6" in result.output


def test_a_single_section_can_be_asked_for(tmp_path: Path) -> None:
    result = run_sections(tmp_path, "4")
    assert result.exit_code == 0, result.output
    assert "sections  4-4 of 6" in result.output
    assert "[1/1]" in result.output


def test_the_whole_document_is_not_announced_as_a_range(tmp_path: Path) -> None:
    result = run_sections(tmp_path, "1-6")
    assert result.exit_code == 0, result.output
    assert "sections  " not in result.output


def test_a_partial_run_says_what_to_ask_for_next(tmp_path: Path) -> None:
    result = run_sections(tmp_path, "1-2")
    assert "next      --sections 3-6" in result.output


def test_the_last_range_offers_no_next(tmp_path: Path) -> None:
    result = run_sections(tmp_path, "5-")
    assert "next" not in result.output


def test_a_ranged_run_writes_its_own_files(tmp_path: Path) -> None:
    # Two ranges of the same document must not overwrite each other.
    notes = long_notes(tmp_path)
    out = tmp_path / "out"
    for spec in ("1-2", "3-4"):
        runner.invoke(
            app, ["cards", str(notes), "--llm", "fake", "--sections", spec, "--out", str(out)]
        )

    assert (out / "big.1-2.apkg").exists()
    assert (out / "big.3-4.apkg").exists()


def test_a_full_run_keeps_the_plain_file_name(tmp_path: Path) -> None:
    notes = write_notes(tmp_path)
    out = tmp_path / "out"
    runner.invoke(app, ["cards", str(notes), "--llm", "fake", "--out", str(out)])
    assert (out / "bio.apkg").exists()


@pytest.mark.parametrize("spec", ["0-5", "40-10", "99-100", "abc", "-"])
def test_an_unusable_range_is_refused(tmp_path: Path, spec: str) -> None:
    result = run_sections(tmp_path, spec)
    assert result.exit_code != 0


def test_durations_read_naturally() -> None:
    from notetaker.timing import duration, estimate

    assert duration(45) == "45s"
    assert duration(600) == "10 min"
    assert duration(18000) == "5.0 hours"
    assert "to" in estimate(4)


def test_checking_makes_the_estimate_longer() -> None:
    from notetaker.timing import estimate

    assert estimate(100) != estimate(100, check=True)


# --- surviving an interrupted run --------------------------------------------


class StopsPartWay:
    """Writes cards for a while, then behaves like someone pressing Ctrl-C."""

    name = "stops"

    def __init__(self, after: int = 2) -> None:
        self.after = after
        self.calls = 0

    def complete(self, system, user, schema):
        self.calls += 1
        if self.calls > self.after:
            raise KeyboardInterrupt
        return {
            "cards": [
                {"question": f"What is topic {self.calls}?", "answer": f"Subject {self.calls}"}
            ]
        }


def test_an_interrupted_run_keeps_what_it_had(tmp_path: Path, monkeypatch) -> None:
    from notetaker import cli

    monkeypatch.setattr(cli, "_build_client", lambda *a, **k: StopsPartWay(after=2))
    notes = long_notes(tmp_path, 6)
    out = tmp_path / "out"

    result = runner.invoke(app, ["cards", str(notes), "--out", str(out)])

    assert (out / "big.apkg").exists(), "the deck should survive the interruption"
    assert (out / "big.tsv").exists()
    assert "What is topic 1?" in (out / "big.tsv").read_text(encoding="utf-8")
    assert result.exit_code == 130


def test_an_interrupted_run_says_where_to_resume(tmp_path: Path, monkeypatch) -> None:
    from notetaker import cli

    monkeypatch.setattr(cli, "_build_client", lambda *a, **k: StopsPartWay(after=2))
    notes = long_notes(tmp_path, 6)

    result = runner.invoke(app, ["cards", str(notes), "--out", str(tmp_path / "out")])

    assert "stopped   after section 3 of 6" in result.output
    assert "resume    --sections 4-6" in result.output


def test_an_interrupt_before_any_cards_says_so(tmp_path: Path, monkeypatch) -> None:
    from notetaker import cli

    monkeypatch.setattr(cli, "_build_client", lambda *a, **k: StopsPartWay(after=0))
    notes = long_notes(tmp_path, 6)

    result = runner.invoke(app, ["cards", str(notes), "--out", str(tmp_path / "out")])

    assert "nothing had been generated yet" in result.output


def test_a_resumed_range_keeps_its_own_files(tmp_path: Path, monkeypatch) -> None:
    from notetaker import cli

    monkeypatch.setattr(cli, "_build_client", lambda *a, **k: StopsPartWay(after=99))
    notes = long_notes(tmp_path, 6)
    out = tmp_path / "out"

    runner.invoke(app, ["cards", str(notes), "--sections", "4-6", "--out", str(out)])

    assert (out / "big.4-6.apkg").exists()


def test_cards_are_written_before_the_run_ends(tmp_path: Path) -> None:
    """The point of saving per section: the file exists while work continues."""
    from notetaker.chunking import chunk_markdown
    from notetaker.generate import generate_cards

    seen: list[int] = []

    class Client:
        name = "stub"

        def complete(self, system, user, schema):
            return {"cards": [{"question": "What is osmosis?", "answer": "Diffusion of water"}]}

    notes = long_notes(tmp_path, 4).read_text(encoding="utf-8")
    generate_cards(
        chunk_markdown(notes),
        Client(),
        on_section=lambda result, number: seen.append(len(result.cards)),
    )

    # One callback per section, each seeing more than the last.
    assert len(seen) == 4
    assert seen == sorted(seen)
    assert seen[0] >= 1
