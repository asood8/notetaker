"""Command-line entry point."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from notetaker import __version__
from notetaker.chunking import DEFAULT_MAX_CHARS, Chunk, chunk_markdown
from notetaker.export import write_apkg, write_tsv
from notetaker.generate import (
    DEFAULT_MAX_CARDS_PER_CHUNK,
    GenerationResult,
    generate_cards,
)
from notetaker.llm import FakeLLM, OllamaLLM
from notetaker.llm.base import LLMClient
from notetaker.llm.ollama import DEFAULT_MODEL, DEFAULT_NUM_CTX, DEFAULT_TIMEOUT

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
        typer.Argument(help="Markdown or text file to read.", exists=True, dir_okay=False),
    ],
    out: Annotated[Path, typer.Option("--out", "-o", help="Directory to write into.")] = Path(
        "out"
    ),
    backend: Annotated[
        str, typer.Option("--llm", help="Model backend: 'ollama' or 'fake'.")
    ] = "ollama",
    model: Annotated[str, typer.Option("--model", help="Ollama model tag.")] = DEFAULT_MODEL,
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
    deck: Annotated[
        str | None, typer.Option("--deck", help="Anki deck name. Defaults to the file name.")
    ] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", help="Extra tag; repeatable.")] = None,
) -> None:
    """Generate flashcards from a notes file."""
    client = _build_client(backend, model=model, num_ctx=num_ctx, timeout=timeout)

    text = notes.read_text(encoding="utf-8")
    chunks = chunk_markdown(text, max_chars=chunk_chars)
    if not chunks:
        typer.secho(f"{notes} has no usable content.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"  reading   {notes}  ({len(chunks)} sections, {len(text)} chars)")
    typer.echo(f"  model     {client.name}")
    typer.echo("")

    result = generate_cards(
        chunks,
        client,
        max_cards_per_chunk=max_cards,
        extra_tags=tag or [],
        on_chunk=_progress(len(chunks)),
    )

    typer.echo("")
    if not result.cards:
        typer.secho("  no cards were generated.", fg=typer.colors.RED, err=True)
        _report_failures(result)
        raise typer.Exit(code=1)

    typer.echo(f"  generated {len(result.cards)} cards{_notes_on(result)}")

    deck_name = deck or notes.stem
    apkg_path = write_apkg(result.cards, out / f"{notes.stem}.apkg", deck_name)
    tsv_path = write_tsv(result.cards, out / f"{notes.stem}.tsv")

    typer.echo("")
    typer.echo(f"  {apkg_path}   double-click to import")
    typer.echo(f"  {tsv_path}   or use File > Import")


def _progress(total: int) -> Callable[[Chunk, int], None]:
    """Print a line per section. Local models are slow enough to need it."""
    state = {"done": 0}

    def report(chunk: Chunk, added: int) -> None:
        state["done"] += 1
        label = chunk.tag or "(no heading)"
        plural = "" if added == 1 else "s"
        typer.echo(f"  [{state['done']}/{total}] {label}  ->  {added} card{plural}")

    return report


def _build_client(backend: str, *, model: str, num_ctx: int, timeout: float) -> LLMClient:
    if backend == "fake":
        return FakeLLM()
    if backend == "ollama":
        return OllamaLLM(model, num_ctx=num_ctx, timeout=timeout)
    raise typer.BadParameter(f"unknown backend {backend!r}; expected 'ollama' or 'fake'")


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
        ("invalid", result.invalid_responses),
        ("failed", result.failed_chunks),
    )
    parts = [f"{count} {label}" for label, count in counts if count]
    return f"  ({', '.join(parts)} dropped)" if parts else ""


if __name__ == "__main__":
    app()
