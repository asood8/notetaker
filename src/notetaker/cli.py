"""Command-line entry point."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from notetaker import __version__
from notetaker.chunking import DEFAULT_MAX_CHARS, Chunk, chunk_markdown
from notetaker.export import write_apkg, write_rejects, write_tsv
from notetaker.generate import (
    DEFAULT_MAX_CARDS_PER_CHUNK,
    GenerationResult,
    generate_cards,
)
from notetaker.llm import FakeLLM, OllamaLLM
from notetaker.llm.base import LLMClient
from notetaker.llm.ollama import (
    DEFAULT_MODEL,
    DEFAULT_NUM_CTX,
    DEFAULT_TIMEOUT,
    is_reasoning_model,
)
from notetaker.ocr import (
    DEFAULT_DPI,
    DEFAULT_VISION_MODEL,
    OcrError,
    read_pdf_with_ocr,
)
from notetaker.ocr import (
    DEFAULT_TIMEOUT as DEFAULT_OCR_TIMEOUT,
)
from notetaker.reader import UnreadableNotes, read_notes
from notetaker.styles import STYLES, Style
from notetaker.timing import estimate
from notetaker.verify import check_cards

SECTION_RANGE_RE = re.compile(r"^(\d*)\s*-\s*(\d*)$")

MAX_LISTED_SECTIONS = 30

app = typer.Typer(
    help="Turn notes into Anki flashcards using a local LLM.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Turn notes into Anki flashcards using a local LLM."""


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


@app.command()
def cards(
    notes: Annotated[
        Path,
        typer.Argument(help="Markdown, text or PDF file to read.", exists=True, dir_okay=False),
    ],
    out: Annotated[Path, typer.Option("--out", "-o", help="Directory to write into.")] = Path(
        "out"
    ),
    backend: Annotated[
        str, typer.Option("--llm", help="Model backend: 'ollama' or 'fake'.")
    ] = "ollama",
    model: Annotated[str, typer.Option("--model", help="Ollama model tag.")] = DEFAULT_MODEL,
    card_style: Annotated[
        str, typer.Option("--style", help="Card style: 'basic' or 'cloze'.")
    ] = "basic",
    max_cards: Annotated[
        int, typer.Option("--max-cards", help="Cards per section.")
    ] = DEFAULT_MAX_CARDS_PER_CHUNK,
    chunk_chars: Annotated[
        int, typer.Option("--chunk-chars", help="Characters of notes per model call.")
    ] = DEFAULT_MAX_CHARS,
    num_ctx: Annotated[
        int, typer.Option("--num-ctx", help="Ollama context window, in tokens.")
    ] = DEFAULT_NUM_CTX,
    timeout: Annotated[
        float, typer.Option("--timeout", help="Seconds to wait per model call.")
    ] = DEFAULT_TIMEOUT,
    ocr: Annotated[
        bool,
        typer.Option("--ocr", help="Read a scanned PDF with a local vision model."),
    ] = False,
    ocr_model: Annotated[
        str, typer.Option("--ocr-model", help="Vision model used for scans.")
    ] = DEFAULT_VISION_MODEL,
    ocr_dpi: Annotated[
        int, typer.Option("--ocr-dpi", help="Resolution pages are rendered at.")
    ] = DEFAULT_DPI,
    ocr_timeout: Annotated[
        float, typer.Option("--ocr-timeout", help="Seconds to wait per scanned page.")
    ] = DEFAULT_OCR_TIMEOUT,
    check: Annotated[
        bool,
        typer.Option("--check", help="Check each card against the notes it came from."),
    ] = False,
    sections: Annotated[
        str | None,
        typer.Option(
            "--sections",
            help="Which sections to use: 10-40, 10-, -3 for the first three, or 12.",
        ),
    ] = None,
    deck: Annotated[
        str | None, typer.Option("--deck", help="Anki deck name. Defaults to the file name.")
    ] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", help="Extra tag; repeatable.")] = None,
) -> None:
    """Generate flashcards from a notes file."""
    client = _build_client(backend, model=model, num_ctx=num_ctx, timeout=timeout)
    style = _build_style(card_style)

    try:
        reader = _ocr_reader(ocr_model, ocr_dpi, ocr_timeout) if ocr else None
        text = read_notes(notes, ocr=reader, on_notice=_notice)
    except (UnreadableNotes, OcrError) as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    chunks = chunk_markdown(text, max_chars=chunk_chars)
    if not chunks:
        typer.secho(f"{notes} has no usable content.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    total_sections = len(chunks)
    first, last = parse_sections(sections, total_sections) if sections else (1, total_sections)
    chunks = chunks[first - 1 : last]
    ranged = (first, last) != (1, total_sections)

    if ranged:
        typer.secho(
            f"  sections  {first}-{last} of {total_sections}",
            fg=typer.colors.YELLOW,
        )

    typer.echo(f"  reading   {notes}  ({len(chunks)} sections, {len(text)} chars)")
    typer.echo(f"  model     {client.name}")
    typer.echo(f"  style     {style.name}")
    if backend == "ollama":
        typer.echo(f"  estimate  {estimate(len(chunks), check=check)}")
    if check:
        typer.echo("  checking  every card is read back against its section")
    if backend == "ollama" and is_reasoning_model(model):
        typer.secho(
            f"  warning   {model} reasons before answering and takes minutes"
            " per section. Try --model llama3.2 instead.",
            fg=typer.colors.YELLOW,
        )
    typer.echo("")

    # A range goes in the file name. Working through a document a lecture at a
    # time otherwise means each run quietly overwrites the last one's deck.
    stem = f"{notes.stem}.{first}-{last}" if ranged else notes.stem
    saver = _Saver(out, stem, deck or notes.stem)

    try:
        result = generate_cards(
            chunks,
            client,
            style=style,
            max_cards_per_chunk=max_cards,
            extra_tags=tag or [],
            check=(lambda cards, passage: check_cards(cards, passage, client)) if check else None,
            on_chunk=_progress(len(chunks)),
            on_section=saver,
        )
    except KeyboardInterrupt:
        _report_interrupted(saver, first, last, total_sections)
        raise typer.Exit(code=130) from None

    typer.echo("")
    if not result.cards:
        typer.secho("  no cards were generated.", fg=typer.colors.RED, err=True)
        _report_failures(result)
        raise typer.Exit(code=1)

    typer.echo(f"  generated {len(result.cards)} cards{_notes_on(result)}")
    _report_files(saver)

    if last < total_sections:
        typer.echo("")
        typer.echo(f"  next      --sections {last + 1}-{total_sections}")


@app.command()
def inspect(
    notes: Annotated[
        Path,
        typer.Argument(help="Markdown, text or PDF file to read.", exists=True, dir_okay=False),
    ],
    chunk_chars: Annotated[
        int, typer.Option("--chunk-chars", help="Characters of notes per model call.")
    ] = DEFAULT_MAX_CHARS,
    ocr: Annotated[
        bool, typer.Option("--ocr", help="Read a scanned PDF with a local vision model.")
    ] = False,
    ocr_model: Annotated[
        str, typer.Option("--ocr-model", help="Vision model used for scans.")
    ] = DEFAULT_VISION_MODEL,
    sections: Annotated[
        str | None,
        typer.Option("--sections", help="Which sections to list, e.g. 100-160 or 31-."),
    ] = None,
) -> None:
    """Show how a file will be split up, without calling a model.

    Worth running first on anything long or unfamiliar. It answers the
    questions that decide whether a run is worth starting: how many sections
    there are, what they will be tagged, and how long it is likely to take.
    """
    try:
        reader = _ocr_reader(ocr_model, DEFAULT_DPI, 300.0) if ocr else None
        text = read_notes(notes, ocr=reader, on_notice=_notice)
    except (UnreadableNotes, OcrError) as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    chunks = chunk_markdown(text, max_chars=chunk_chars)
    if not chunks:
        typer.secho(f"{notes} has no usable content.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"  reading   {notes}  ({len(chunks)} sections, {len(text):,} chars)")
    typer.echo("")

    # Without a range, show an opening sample. With one, show all of it: the
    # reason to ask for a range is to read it.
    if sections:
        first, last = parse_sections(sections, len(chunks))
    else:
        first, last = 1, min(MAX_LISTED_SECTIONS, len(chunks))

    for number in range(first, last + 1):
        chunk = chunks[number - 1]
        label = chunk.tag or "(no heading)"
        typer.echo(f"  [{number:>3}] {label:<44} {len(chunk.text):>6,} chars")

    hidden = len(chunks) - last
    if hidden > 0:
        typer.echo(f"        and {hidden} more, with --sections {last + 1}-")

    untagged = sum(1 for chunk in chunks if not chunk.tag)
    largest = max(len(chunk.text) for chunk in chunks)

    typer.echo("")
    typer.echo(f"  largest   {largest:,} chars")
    if untagged:
        typer.secho(
            f"  untagged  {untagged} section(s) have no heading above them, "
            "so their cards will only carry the tags you pass with --tag",
            fg=typer.colors.YELLOW,
        )
    typer.echo(f"  estimate  {estimate(len(chunks))} to generate")
    typer.echo(f"            {estimate(len(chunks), check=True)} with --check")


def parse_sections(spec: str, total: int) -> tuple[int, int]:
    """Turn `10-40`, `10-`, `-3` or `12` into an inclusive, 1-based pair.

    The numbering is the one `inspect` prints, so a range can be copied
    straight off that listing. Working through a long document one lecture at
    a time is the point: a 497-section deck is hours in one go, and no way to
    ask for the middle of it would make that an all-or-nothing run.
    """
    text = spec.strip()

    if text.isdigit():
        first = last = int(text)
    else:
        match = SECTION_RANGE_RE.match(text)
        if match is None or not any(match.groups()):
            raise typer.BadParameter(
                f"cannot read {spec!r}; use 10-40, 10-, -3 for the first three, or 12"
            )
        start, stop = match.groups()
        first = int(start) if start else 1
        last = int(stop) if stop else total

    if first < 1:
        raise typer.BadParameter("sections are numbered from 1")
    if first > last:
        raise typer.BadParameter(f"{first}-{last} runs backwards")
    if first > total:
        raise typer.BadParameter(f"there are only {total} sections")

    return first, min(last, total)


def _progress(total: int) -> Callable[[Chunk, int], None]:
    """Print a line per section. Local models are slow enough to need it."""
    state = {"done": 0}

    def report(chunk: Chunk, added: int) -> None:
        state["done"] += 1
        label = chunk.tag or "(no heading)"
        plural = "" if added == 1 else "s"
        typer.echo(f"  [{state['done']}/{total}] {label}  ->  {added} card{plural}")

    return report


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host", help="Address to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port to listen on.")] = 8000,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the page in your browser.")
    ] = True,
) -> None:
    """Open a local page for dropping notes onto."""
    try:
        import uvicorn

        from notetaker.web import create_app
    except ImportError as exc:
        typer.secho(
            "  The web UI needs extra packages: pip install 'notetaker[web]'",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    address = f"http://{'127.0.0.1' if host in {'0.0.0.0', '::'} else host}:{port}"
    typer.echo(f"  notetaker is at {address}")
    typer.echo("  close this window when you are finished")

    if open_browser:
        # Give uvicorn a moment to bind, otherwise the browser lands on a
        # connection error and the person assumes it is broken.
        import threading
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open(address)).start()

    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


def _build_client(backend: str, *, model: str, num_ctx: int, timeout: float) -> LLMClient:
    if backend == "fake":
        return FakeLLM()
    if backend == "ollama":
        return OllamaLLM(model, num_ctx=num_ctx, timeout=timeout)
    raise typer.BadParameter(f"unknown backend {backend!r}; expected 'ollama' or 'fake'")


class _Saver:
    """Writes the deck out after every section.

    A run over a few hundred sections takes hours. Holding everything until
    the end means a closed window, a flat battery or a stray Ctrl-C throws all
    of it away, which is exactly the run you least want to repeat. Writing
    each time costs about 90ms, or well under a percent of a long run.
    """

    def __init__(self, out: Path, stem: str, deck_name: str) -> None:
        self.out = out
        self.stem = stem
        self.deck_name = deck_name
        self.section = 0
        self.cards = 0
        self.apkg: Path | None = None
        self.tsv: Path | None = None
        self.rejects: Path | None = None

    def __call__(self, result: GenerationResult, number: int) -> None:
        self.section = number
        if len(result.cards) == self.cards and not result.rejected:
            return

        self.cards = len(result.cards)
        if result.cards:
            self.apkg = write_apkg(result.cards, self.out / f"{self.stem}.apkg", self.deck_name)
            self.tsv = write_tsv(result.cards, self.out / f"{self.stem}.tsv")
        if result.rejected:
            self.rejects = write_rejects(result.rejected, self.out / f"{self.stem}.dropped.tsv")


def _report_files(saver: _Saver) -> None:
    typer.echo("")
    if saver.apkg:
        typer.echo(f"  {saver.apkg}   double-click to import")
    if saver.tsv:
        typer.echo(f"  {saver.tsv}   or use File > Import")
    if saver.rejects:
        typer.echo(f"  {saver.rejects}   what was thrown away, and why")


def _report_interrupted(saver: _Saver, first: int, last: int, total: int) -> None:
    """Say what survived and how to pick the run back up."""
    reached = first - 1 + saver.section
    typer.echo("")
    typer.secho(f"  stopped   after section {reached} of {total}", fg=typer.colors.YELLOW)

    if not saver.cards:
        typer.echo("  nothing had been generated yet, so nothing was saved")
        return

    typer.echo(f"  saved     {saver.cards} cards from the sections that finished")
    _report_files(saver)
    if reached < last:
        typer.echo("")
        typer.echo(f"  resume    --sections {reached + 1}-{last}")


def _notice(message: str) -> None:
    """Something the reader had to work around, worth knowing but not fatal."""
    typer.secho(f"  note      {message}", fg=typer.colors.YELLOW)


def _ocr_reader(model: str, dpi: int, timeout: float) -> Callable[[Path], str]:
    """Read a scan page by page, saying so as it goes. Each page is a model call."""

    def read(path: Path) -> str:
        typer.secho(
            f"  scan      no text layer; reading with {model}. "
            "This is slow, and a vision model can misread a word confidently.",
            fg=typer.colors.YELLOW,
        )

        def page(number: int, total: int) -> None:
            typer.echo(f"  page      {number}/{total}")

        return read_pdf_with_ocr(path, model=model, dpi=dpi, timeout=timeout, on_page=page)

    return read


def _build_style(name: str) -> Style:
    try:
        return STYLES[name]
    except KeyError:
        expected = " or ".join(repr(key) for key in STYLES)
        raise typer.BadParameter(f"unknown style {name!r}; expected {expected}") from None


def _report_failures(result: GenerationResult) -> None:
    if result.failed_chunks:
        typer.secho(
            f"  {result.failed_chunks} section(s) failed. Is the model pulled and Ollama running?",
            fg=typer.colors.RED,
            err=True,
        )


def _notes_on(result: GenerationResult) -> str:
    counts = (
        ("duplicate", result.duplicates),
        ("low-quality", result.low_quality),
        ("admin section", result.skipped_sections),
        ("unsupported", result.unsupported),
        ("invalid", result.invalid_responses),
        ("failed", result.failed_chunks),
    )
    parts = [f"{count} {label}" for label, count in counts if count]
    return f"  ({', '.join(parts)} dropped)" if parts else ""


if __name__ == "__main__":
    app()
