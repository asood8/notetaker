"""Split markdown notes into pieces small enough for a local model."""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
PARAGRAPH_RE = re.compile(r"\n\s*\n")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

DEFAULT_MAX_CHARS = 4000
"""Roughly 1k tokens. Small enough that an 8B model keeps the whole chunk in view."""


@dataclass(frozen=True)
class Chunk:
    """A span of notes plus the heading trail it was found under."""

    text: str
    heading_path: tuple[str, ...]

    @property
    def tag(self) -> str:
        """The heading trail as a hierarchical Anki tag, e.g. `Biology::Cell_Cycle`."""
        return "::".join(_slug(part) for part in self.heading_path)


def chunk_markdown(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    """Split `text` at heading boundaries, then further split anything oversized."""
    chunks: list[Chunk] = []
    for path, body in _split_sections(text):
        stripped = body.strip()
        if not stripped:
            continue
        chunks.extend(
            Chunk(text=piece, heading_path=path) for piece in _split_to_size(stripped, max_chars)
        )
    return chunks


def _split_sections(text: str) -> list[tuple[tuple[str, ...], str]]:
    """Walk the document, tracking the heading stack. Fenced code is left alone."""
    sections: list[tuple[tuple[str, ...], str]] = []
    stack: list[str] = []
    body: list[str] = []
    in_fence = False

    def flush() -> None:
        if body:
            sections.append((tuple(stack), "\n".join(body)))
            body.clear()

    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            body.append(line)
            continue

        heading = None if in_fence else HEADING_RE.match(line)
        if heading is None:
            body.append(line)
            continue

        flush()
        level = len(heading.group(1))
        del stack[level - 1 :]
        stack.append(heading.group(2).strip())

    flush()
    return sections


def _split_to_size(body: str, max_chars: int) -> list[str]:
    """Pack paragraphs into pieces of at most `max_chars`."""
    if len(body) <= max_chars:
        return [body]

    pieces: list[str] = []
    current: list[str] = []
    size = 0

    for raw in PARAGRAPH_RE.split(body):
        para = raw.strip()
        if not para:
            continue

        if len(para) > max_chars:
            if current:
                pieces.append("\n\n".join(current))
                current, size = [], 0
            pieces.extend(_split_paragraph(para, max_chars))
            continue

        if current and size + len(para) > max_chars:
            pieces.append("\n\n".join(current))
            current, size = [], 0

        current.append(para)
        size += len(para) + 2

    if current:
        pieces.append("\n\n".join(current))
    return pieces


def _split_paragraph(para: str, max_chars: int) -> list[str]:
    """Last resort for a single paragraph that is too long: split on sentences."""
    pieces: list[str] = []
    current = ""

    for sentence in SENTENCE_RE.split(para):
        if current and len(current) + len(sentence) + 1 > max_chars:
            pieces.append(current.strip())
            current = ""
        current = f"{current} {sentence}".strip()
        while len(current) > max_chars:
            pieces.append(current[:max_chars])
            current = current[max_chars:]

    if current.strip():
        pieces.append(current.strip())
    return pieces


def _slug(heading: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", heading).strip()
    return re.sub(r"\s+", "_", cleaned) or "untitled"
