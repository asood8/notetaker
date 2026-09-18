"""Reading notes out of whatever the user points us at.

Markdown is the format this tool is built around: headings become deck tags
and chunk boundaries. A PDF has no headings as such, but it usually has them
visually -- a short line on its own, set apart from the paragraphs around it.
Those are recovered and rewritten as markdown headings, which is recovering
structure the document really has. Page numbers are not: a synthetic "Page 7"
tag would look like organization without being any, so pages are not marked.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".text", ""})
PDF_SUFFIX = ".pdf"

HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")
BLANK_LINE_RE = re.compile(r"\n\s*\n")
TRAILING_SPACE_RE = re.compile(r"[ \t]+\n")
BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s")
SENTENCE_END_RE = re.compile(r"[.,;:!?]$")
LETTER_RE = re.compile(r"[A-Za-z]")

MAX_HEADING_CHARS = 60
"""A line longer than this is prose, however it is punctuated."""


class UnreadableNotes(Exception):
    """The file exists but its text could not be used."""


def read_notes(path: Path, *, ocr: Callable[[Path], str] | None = None) -> str:
    """Return the text of `path`, whatever readable format it is in.

    `ocr` is a fallback for PDFs with no text layer. It is passed in rather
    than imported so that this module knows nothing about vision models, and
    so the caller decides whether reading a scan is wanted at all.
    """
    suffix = path.suffix.lower()

    if suffix == PDF_SUFFIX:
        return read_pdf(path, ocr=ocr)
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8")

    supported = ", ".join(sorted(s for s in TEXT_SUFFIXES if s)) + f", {PDF_SUFFIX}"
    raise UnreadableNotes(
        f"cannot read {suffix or 'a file with no extension'}; expected {supported}"
    )


def read_pdf(path: Path, *, ocr: Callable[[Path], str] | None = None) -> str:
    """Extract the text layer of a PDF, falling back to `ocr` if there is none."""
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise UnreadableNotes("reading PDFs needs pypdf installed") from exc

    try:
        reader = PdfReader(path)
    except PdfReadError as exc:
        raise UnreadableNotes(f"{path.name} is not a readable PDF: {exc}") from exc

    if reader.is_encrypted and not _try_unlock(reader):
        raise UnreadableNotes(f"{path.name} is password protected.")

    pages = []
    for page in reader.pages:
        # Layout mode keeps the blank lines between paragraphs. The default
        # mode drops them, which collapses a whole page into one run-on block.
        extracted = page.extract_text(extraction_mode="layout") or ""
        cleaned = clean_extracted(extracted)
        if cleaned:
            pages.append(cleaned)

    text = "\n\n".join(pages)
    if text.strip():
        return text

    if ocr is None:
        raise UnreadableNotes(
            f"{path.name} has no text layer, so it is probably a scan. "
            "Pass --ocr to read it with a local vision model."
        )
    return clean_extracted(ocr(path))


def _try_unlock(reader) -> bool:
    """Some PDFs are 'encrypted' with an empty owner password."""
    try:
        return bool(reader.decrypt(""))
    except Exception:
        return False


def clean_extracted(text: str) -> str:
    """Undo the line breaks a PDF's layout imposes on its sentences.

    Extracted text is broken at the width of the page, not at the end of
    sentences, and words are hyphenated across those breaks. Left alone, the
    chunker would hand the model fragments.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = HYPHEN_BREAK_RE.sub(r"\1\2", text)
    text = TRAILING_SPACE_RE.sub("\n", text)

    blocks = []
    for block in BLANK_LINE_RE.split(text):
        joined = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if joined:
            blocks.append((joined, looks_like_heading(block, joined)))

    return "\n\n".join(_mark_headings(blocks))


def _mark_headings(blocks: list[tuple[str, bool]]) -> list[str]:
    """Promote heading candidates, but only where they actually head something.

    A heading with no prose after it is not a heading -- it is a short last
    line, or a caption. Walking backwards makes this one pass: consecutive
    candidates (a title above a subtitle) are all kept, as long as prose
    eventually follows them.
    """
    marked: list[str] = []
    prose_follows = False

    for joined, candidate in reversed(blocks):
        if candidate and prose_follows:
            marked.append(f"## {joined}")
        else:
            marked.append(joined)
            prose_follows = True

    return list(reversed(marked))


def looks_like_heading(block: str, joined: str) -> bool:
    """Guess whether a block was a heading on the page.

    Deliberately narrow: a single short line, standing alone, not punctuated
    like a sentence and not part of a list. A wrong guess costs one stray tag,
    so this errs towards calling things prose.
    """
    if len(block.strip().splitlines()) != 1:
        return False
    if len(joined) > MAX_HEADING_CHARS:
        return False
    if BULLET_RE.match(joined) or SENTENCE_END_RE.search(joined):
        return False
    return bool(LETTER_RE.search(joined))
