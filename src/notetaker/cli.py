"""Command-line entry point."""

from __future__ import annotations

import typer

from notetaker import __version__

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


if __name__ == "__main__":
    app()
