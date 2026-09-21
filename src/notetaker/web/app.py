"""A local web front end for the same pipeline the CLI drives.

The page works in two steps, and the first one matters more than it looks.
Dropping a file reads and splits it without calling a model, which is quick,
and reports back what is actually there: how many sections, what they are
called, how long generating them would take. A 500-section slide deck is
several hours of work, and nobody should discover that after starting.

Generation itself takes minutes, which rules out doing it inside the request
that starts it. A job runs in a background thread and the page polls for
progress, so it can show sections resolving one at a time instead of a spinner
that says nothing.

This server is meant to be reachable from the machine it runs on and nowhere
else. It binds to localhost, and it never writes anything outside a temporary
directory it owns.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import ValidationError

from notetaker.chunking import DEFAULT_MAX_CHARS, Chunk, chunk_markdown
from notetaker.export import write_apkg, write_rejects, write_tsv
from notetaker.generate import DEFAULT_MAX_CARDS_PER_CHUNK, generate_cards
from notetaker.llm import FakeLLM, OllamaLLM
from notetaker.llm.ollama import DEFAULT_MODEL, is_reasoning_model
from notetaker.models import Card, CardType
from notetaker.ocr import DEFAULT_VISION_MODEL, OcrError, read_pdf_with_ocr
from notetaker.reader import UnreadableNotes, read_notes
from notetaker.styles import STYLES
from notetaker.timing import CHECK_OVERHEAD, SECONDS_PER_SECTION, estimate
from notetaker.verify import check_cards

STATIC = Path(__file__).resolve().parent / "static"

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
"""Large enough for a whole semester of lecture slides."""

ALLOWED_SUFFIXES = {".md", ".markdown", ".txt", ".text", ".pdf"}


@dataclass
class Preview:
    """A file that has been read and split, but not yet turned into cards.

    The extracted text is kept because pulling it back out of a big PDF takes
    the better part of a minute, and making someone wait through that twice
    for one deck would be silly.
    """

    id: str
    name: str
    path: Path
    text: str
    chunks: list[Chunk]
    notices: list[str]

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "total": len(self.chunks),
            "chars": len(self.text),
            "notices": self.notices,
            "estimate": estimate(len(self.chunks)),
            "estimate_checked": estimate(len(self.chunks), check=True),
            # Handed over so the page can re-estimate a chosen range without
            # asking the server, and without a second copy of the numbers.
            "seconds_per_section": list(SECONDS_PER_SECTION),
            "check_overhead": CHECK_OVERHEAD,
            "sections": [
                {
                    "number": number,
                    "tag": chunk.tag or "(no heading)",
                    "chars": len(chunk.text),
                }
                for number, chunk in enumerate(self.chunks, start=1)
            ],
        }


@dataclass
class Job:
    """One generation run, and everything the page needs to render it."""

    id: str
    name: str
    style: str
    model: str
    first: int = 1
    last: int = 1
    state: str = "running"
    total: int = 0
    done: int = 0
    sections: list[dict[str, Any]] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    directory: Path | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "style": self.style,
            "model": self.model,
            "state": self.state,
            "total": self.total,
            "done": self.done,
            "first": self.first,
            "last": self.last,
            "sections": list(self.sections),
            "counts": dict(self.counts),
            "error": self.error,
            "rejected": list(self.rejected),
            "cards": [
                {
                    "question": card.question,
                    "answer": card.answer,
                    "tags": list(card.tags),
                    "card_type": str(card.card_type),
                }
                for card in self.cards
            ],
        }


class Registry:
    """In-memory storage. One process, one user, no database."""

    def __init__(self) -> None:
        self._items: dict[str, Any] = {}
        self._lock = threading.Lock()

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[key] = value

    def get(self, key: str, what: str) -> Any:
        with self._lock:
            item = self._items.get(key)
        if item is None:
            raise HTTPException(status_code=404, detail=f"No such {what}.")
        return item

    def values(self) -> list[Any]:
        with self._lock:
            return list(self._items.values())

    def update(self, item: Any, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(item, key, value)


def create_app() -> FastAPI:
    previews = Registry()
    jobs = Registry()
    workspace = Path(tempfile.mkdtemp(prefix="notetaker-web-"))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    app = FastAPI(title="notetaker", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/models")
    def models() -> dict[str, Any]:
        """What the local Ollama has pulled, so the page can offer real choices."""
        import httpx

        try:
            response = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
            response.raise_for_status()
            names = [model["name"] for model in response.json().get("models", [])]
        except Exception:
            return {"available": False, "models": [], "default": DEFAULT_MODEL}

        return {
            "available": True,
            "default": DEFAULT_MODEL,
            "models": [{"name": name, "slow": is_reasoning_model(name)} for name in sorted(names)],
        }

    @app.post("/api/preview")
    async def preview(
        file: UploadFile,
        ocr: bool = Form(False),
        ocr_model: str = Form(DEFAULT_VISION_MODEL),
        chunk_chars: int = Form(DEFAULT_MAX_CHARS),
    ) -> dict[str, Any]:
        """Read and split a file without calling a model. Cheap, and honest."""
        name = Path(file.filename or "notes").name
        if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=400, detail="Upload a .md, .txt or .pdf file.")

        payload = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(payload) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="That file is larger than 200 MB.")

        identifier = uuid.uuid4().hex
        directory = workspace / identifier
        directory.mkdir(parents=True, exist_ok=True)
        source = directory / name
        source.write_bytes(payload)

        notices: list[str] = []
        reader = _ocr_reader(ocr_model) if ocr else None

        try:
            text = read_notes(source, ocr=reader, on_notice=notices.append)
        except UnreadableNotes as exc:
            # A scan is not a failure, it is a question: shall we read the
            # pictures? That costs real time, so the page asks rather than
            # deciding for them.
            if "scan" in str(exc):
                return {"needs_ocr": True, "message": str(exc), "name": name}
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OcrError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        chunks = chunk_markdown(text, max_chars=chunk_chars)
        if not chunks:
            raise HTTPException(status_code=400, detail="That file has no readable notes in it.")

        record = Preview(identifier, name, source, text, chunks, notices)
        previews.put(identifier, record)
        return record.summary()

    @app.post("/api/preview/{preview_id}/resplit")
    def resplit(preview_id: str, chunk_chars: int = Form(DEFAULT_MAX_CHARS)) -> dict[str, Any]:
        """Split the same text differently, without reading the file again.

        Re-extracting a large PDF costs the better part of a minute, and the
        text has not changed -- only the size we want the pieces cut to.
        """
        record: Preview = previews.get(preview_id, "file")
        chunks = chunk_markdown(record.text, max_chars=max(500, chunk_chars))
        if not chunks:
            raise HTTPException(status_code=400, detail="That leaves nothing to work from.")

        record.chunks = chunks
        return record.summary()

    @app.post("/api/jobs")
    def start(
        preview_id: str = Form(...),
        style: str = Form("basic"),
        model: str = Form(DEFAULT_MODEL),
        backend: str = Form("ollama"),
        deck: str = Form(""),
        tags: str = Form(""),
        max_cards: int = Form(DEFAULT_MAX_CARDS_PER_CHUNK),
        check: bool = Form(False),
        first: int = Form(1),
        last: int = Form(0),
    ) -> dict[str, str]:
        if style not in STYLES:
            raise HTTPException(status_code=400, detail=f"Unknown style {style!r}.")

        record: Preview = previews.get(preview_id, "file")
        total = len(record.chunks)
        last = total if last <= 0 else min(last, total)
        first = max(1, min(first, last))

        job = Job(
            id=uuid.uuid4().hex,
            name=record.name,
            style=style,
            model=model,
            first=first,
            last=last,
            total=last - first + 1,
            directory=record.path.parent,
        )
        jobs.put(job.id, job)

        threading.Thread(
            target=_run,
            args=(jobs, job, record, backend, deck, tags, max_cards, check),
            daemon=True,
        ).start()
        return {"id": job.id}

    @app.get("/api/jobs")
    def running() -> dict[str, Any]:
        """Any run still in progress, so a reloaded page can find its way back.

        Generation happens in a background thread and keeps going whatever the
        browser does. Losing the tab used to orphan the run: it carried on
        working and writing cards, with no way left to watch it or fetch them.
        """
        unfinished = [job for job in jobs.values() if job.state == "running"]
        return {
            "running": [
                {"id": job.id, "name": job.name, "done": job.done, "total": job.total}
                for job in unfinished
            ]
        }

    @app.get("/api/jobs/{job_id}")
    def status(job_id: str) -> dict[str, Any]:
        return jobs.get(job_id, "job").snapshot()

    @app.post("/api/jobs/{job_id}/cards")
    def edit_cards(job_id: str, cards: Annotated[list[dict], Body()]) -> dict[str, int]:
        """Replace a job's cards with edited ones and rewrite the deck.

        Dropping a bad card is easy; a card that is nearly right is the common
        case, and retyping it in Anki afterwards defeats the point of the tool.
        """
        job: Job = jobs.get(job_id, "job")
        if job.directory is None:
            raise HTTPException(status_code=409, detail="That deck is not ready yet.")

        try:
            edited = [
                Card(
                    question=entry.get("question", ""),
                    answer=entry.get("answer", ""),
                    tags=list(entry.get("tags") or []),
                    card_type=entry.get("card_type") or CardType.BASIC,
                )
                for entry in cards
            ]
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail="A card was left empty.") from exc

        if not edited:
            raise HTTPException(status_code=400, detail="No cards were given.")

        stem = _stem(job)
        write_apkg(edited, job.directory / f"{stem}.apkg", Path(job.name).stem)
        write_tsv(edited, job.directory / f"{stem}.tsv")
        jobs.update(job, cards=edited)
        return {"cards": len(edited)}

    @app.get("/api/jobs/{job_id}/deck.{extension}")
    def download(job_id: str, extension: str, keep: str | None = None) -> FileResponse:
        if extension not in {"apkg", "tsv", "dropped.tsv"}:
            raise HTTPException(status_code=404, detail="No such file.")

        job: Job = jobs.get(job_id, "job")
        # A run of a few hundred sections takes hours, and the cards are
        # written as they are made, so there is no reason to withhold what is
        # already finished from someone who wants to start studying it.
        if job.directory is None or not job.cards:
            raise HTTPException(status_code=409, detail="No cards have been made yet.")

        # `keep` lets someone untick the cards they do not want before
        # downloading. A model that is right most of the time still needs a
        # way to throw out the times it wasn't, without editing the deck in
        # Anki afterwards.
        if keep is not None and extension != "dropped.tsv":
            return _selected(job, extension, keep)

        path = job.directory / f"{_stem(job)}.{extension}"
        if not path.exists():
            raise HTTPException(status_code=404, detail="No such file.")
        return FileResponse(path, filename=path.name)

    return app


def _selected(job: Job, extension: str, keep: str) -> FileResponse:
    """Write a deck containing only the cards that are still ticked."""
    wanted = []
    for piece in keep.split(","):
        piece = piece.strip()
        if piece.isdigit() and int(piece) < len(job.cards):
            wanted.append(job.cards[int(piece)])

    if not wanted:
        raise HTTPException(status_code=400, detail="No cards were selected.")

    assert job.directory is not None
    path = job.directory / f"{_stem(job)}.selected.{extension}"
    if extension == "apkg":
        write_apkg(wanted, path, Path(job.name).stem)
    else:
        write_tsv(wanted, path)
    return FileResponse(path, filename=f"{_stem(job)}.{extension}")


def _stem(job: Job) -> str:
    stem = Path(job.name).stem
    ranged = (job.first, job.last) != (1, job.total + job.first - 1)
    return f"{stem}.{job.first}-{job.last}" if ranged else stem


def _ocr_reader(model: str):
    def read(path: Path) -> str:
        return read_pdf_with_ocr(path, model=model)

    return read


def _run(
    jobs: Registry,
    job: Job,
    preview: Preview,
    backend: str,
    deck: str,
    tags: str,
    max_cards: int,
    check: bool,
) -> None:
    """The whole pipeline, off the request thread."""
    chunks = preview.chunks[job.first - 1 : job.last]
    client = FakeLLM() if backend == "fake" else OllamaLLM(job.model)
    verifier = (lambda cards, passage: check_cards(cards, passage, client)) if check else None

    def progress(chunk: Chunk, added: int) -> None:
        job.sections.append({"tag": chunk.tag or "(no heading)", "cards": added})
        jobs.update(job, done=job.done + 1)

    stem = _stem(job)
    deck_name = deck.strip() or Path(job.name).stem

    def save(result, number: int) -> None:
        """Write after every section, so an interrupted run still leaves a deck."""
        if len(result.cards) == len(job.cards):
            return
        write_apkg(result.cards, job.directory / f"{stem}.apkg", deck_name)
        write_tsv(result.cards, job.directory / f"{stem}.tsv")
        if result.rejected:
            write_rejects(result.rejected, job.directory / f"{stem}.dropped.tsv")
        jobs.update(job, cards=list(result.cards))

    try:
        result = generate_cards(
            chunks,
            client,
            style=STYLES[job.style],
            max_cards_per_chunk=max_cards,
            extra_tags=[tag for tag in tags.split() if tag],
            check=verifier,
            on_chunk=progress,
            on_section=save,
        )
    except Exception as exc:  # the thread must not die silently
        jobs.update(job, state="error", error=str(exc))
        return

    if not result.cards:
        jobs.update(job, state="error", error=_no_cards_message(result))
        return

    jobs.update(
        job,
        state="done",
        cards=result.cards,
        rejected=[
            {
                "question": item.card.question,
                "answer": item.card.answer,
                "reason": item.reason,
                "tag": item.tag,
            }
            for item in result.rejected
        ],
        counts={
            "duplicates": result.duplicates,
            "low_quality": result.low_quality,
            "skipped_sections": result.skipped_sections,
            "unsupported": result.unsupported,
            "invalid": result.invalid_responses,
            "failed": result.failed_chunks,
        },
    )


def _no_cards_message(result) -> str:
    if result.failed_chunks:
        return "The model could not be reached. Check that Ollama is running."
    if result.invalid_responses:
        return "The model replied with something unusable. Try a different model."
    return "No cards came out of these notes. They may be too short to work from."
