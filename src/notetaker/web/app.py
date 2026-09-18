"""A local web front end for the same pipeline the CLI drives.

Generation takes minutes, which rules out doing the work inside the request
that starts it. A job is started in a background thread and the page polls for
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
from typing import Any

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from notetaker.chunking import DEFAULT_MAX_CHARS, chunk_markdown
from notetaker.export import write_apkg, write_tsv
from notetaker.generate import DEFAULT_MAX_CARDS_PER_CHUNK, generate_cards
from notetaker.llm import FakeLLM, OllamaLLM
from notetaker.llm.ollama import DEFAULT_MODEL
from notetaker.models import Card
from notetaker.reader import UnreadableNotes, read_notes
from notetaker.styles import STYLES

STATIC = Path(__file__).resolve().parent / "static"

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
"""Generous for notes, small enough that a stray file cannot fill the disk."""

ALLOWED_SUFFIXES = {".md", ".markdown", ".txt", ".text", ".pdf"}


@dataclass
class Job:
    """One generation run, and everything the page needs to render it."""

    id: str
    name: str
    style: str
    model: str
    state: str = "running"
    total: int = 0
    done: int = 0
    sections: list[dict[str, Any]] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)
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
            "sections": list(self.sections),
            "counts": dict(self.counts),
            "error": self.error,
            "cards": [
                {
                    "question": card.question,
                    "answer": card.answer,
                    "tags": list(card.tags),
                }
                for card in self.cards
            ],
        }


class Jobs:
    """An in-memory registry. One process, one user, no database."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, **kwargs: Any) -> Job:
        job = Job(id=uuid.uuid4().hex, **kwargs)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="No such job.")
        return job

    def update(self, job: Job, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(job, key, value)


def create_app() -> FastAPI:
    jobs = Jobs()
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
        return {"available": True, "models": sorted(names), "default": DEFAULT_MODEL}

    @app.post("/api/jobs")
    async def start(
        file: UploadFile,
        style: str = Form("basic"),
        model: str = Form(DEFAULT_MODEL),
        backend: str = Form("ollama"),
        deck: str = Form(""),
        tags: str = Form(""),
        max_cards: int = Form(DEFAULT_MAX_CARDS_PER_CHUNK),
    ) -> dict[str, str]:
        if style not in STYLES:
            raise HTTPException(status_code=400, detail=f"Unknown style {style!r}.")

        name = Path(file.filename or "notes").name
        if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail="Upload a .md, .txt or .pdf file.",
            )

        payload = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(payload) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="That file is larger than 20 MB.")

        job = jobs.create(name=name, style=style, model=model)
        directory = workspace / job.id
        directory.mkdir(parents=True, exist_ok=True)
        source = directory / name
        source.write_bytes(payload)
        jobs.update(job, directory=directory)

        thread = threading.Thread(
            target=_run,
            args=(jobs, job, source, backend, deck, tags, max_cards),
            daemon=True,
        )
        thread.start()
        return {"id": job.id}

    @app.get("/api/jobs/{job_id}")
    def status(job_id: str) -> dict[str, Any]:
        return jobs.get(job_id).snapshot()

    @app.get("/api/jobs/{job_id}/deck.{extension}")
    def download(job_id: str, extension: str) -> FileResponse:
        if extension not in {"apkg", "tsv"}:
            raise HTTPException(status_code=404, detail="No such file.")

        job = jobs.get(job_id)
        if job.state != "done" or job.directory is None:
            raise HTTPException(status_code=409, detail="That deck is not ready yet.")

        path = job.directory / f"{Path(job.name).stem}.{extension}"
        if not path.exists():
            raise HTTPException(status_code=404, detail="No such file.")
        return FileResponse(path, filename=path.name)

    return app


def _run(
    jobs: Jobs,
    job: Job,
    source: Path,
    backend: str,
    deck: str,
    tags: str,
    max_cards: int,
) -> None:
    """The whole pipeline, off the request thread."""
    try:
        text = read_notes(source)
    except UnreadableNotes as exc:
        jobs.update(job, state="error", error=str(exc))
        return
    except OSError as exc:
        jobs.update(job, state="error", error=f"Could not read that file: {exc}")
        return

    chunks = chunk_markdown(text, max_chars=DEFAULT_MAX_CHARS)
    if not chunks:
        jobs.update(job, state="error", error="That file has no readable notes in it.")
        return

    jobs.update(job, total=len(chunks))
    client = FakeLLM() if backend == "fake" else OllamaLLM(job.model)

    def progress(chunk, added: int) -> None:
        job.sections.append({"tag": chunk.tag or "(no heading)", "cards": added})
        jobs.update(job, done=job.done + 1)

    try:
        result = generate_cards(
            chunks,
            client,
            style=STYLES[job.style],
            max_cards_per_chunk=max_cards,
            extra_tags=[tag for tag in tags.split() if tag],
            on_chunk=progress,
        )
    except Exception as exc:  # the thread must not die silently
        jobs.update(job, state="error", error=str(exc))
        return

    if not result.cards:
        jobs.update(
            job,
            state="error",
            error=_no_cards_message(result),
        )
        return

    stem = Path(job.name).stem
    assert job.directory is not None
    write_apkg(result.cards, job.directory / f"{stem}.apkg", deck.strip() or stem)
    write_tsv(result.cards, job.directory / f"{stem}.tsv")

    jobs.update(
        job,
        state="done",
        cards=result.cards,
        counts={
            "duplicates": result.duplicates,
            "low_quality": result.low_quality,
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
