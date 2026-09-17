"""Command-line entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from notetaker import __version__
from notetaker.chunking import DEFAULT_MAX_CHARS, chunk_markdown
from notetaker.export import write_tsv
from notetaker.generate import (
    DEFAULT_MAX_CARDS_PER_CHUNK,
    GenerationResult,
    generate_cards,
)
from notetaker.llm import FakeLLM
from notetaker.llm.base import LLMClient

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
        str, typer.Option("--llm", help="Model backend: 'fake' or 'ollama'.")
    ] = "fake",
    max_cards: Annotated[
        int, typer.Option("--max-cards", help="Cards per section.")
    ] = DEFAULT_MAX_CARDS_PER_CHUNK,
    chunk_chars: Annotated[
        int, typer.Option("--chunk-chars", help="Characters of notes per model call.")
    ] = DEFAULT_MAX_CHARS,
    tag: Annotated[list[str] | None, typer.Option("--tag", help="Extra tag; repeatable.")] = None,
) -> None:
    """Generate flashcards from a notes file."""
    client = _build_client(backend)

    text = notes.read_text(encoding="utf-8")
    chunks = chunk_markdown(text, max_chars=chunk_chars)
    if not chunks:
        typer.secho(f"{notes} has no usable content.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"  reading   {notes}  ({len(chunks)} sections, {len(text)} chars)")
    typer.echo(f"  model     {client.name}")

    result = generate_cards(
        chunks,
        client,
        max_cards_per_chunk=max_cards,
        extra_tags=tag or [],
    )

    if not result.cards:
        typer.secho("  no cards were generated.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"  generated {len(result.cards)} cards{_notes_on(result)}")

    tsv_path = write_tsv(result.cards, out / f"{notes.stem}.tsv")
    typer.echo("")
    typer.echo(f"  {tsv_path}   File > Import in Anki")


def _build_client(backend: str) -> LLMClient:
    if backend == "fake":
        return FakeLLM()
    if backend == "ollama":
        raise typer.BadParameter("the ollama backend is not wired up yet; use --llm fake")
    raise typer.BadParameter(f"unknown backend {backend!r}; expected 'fake' or 'ollama'")


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
