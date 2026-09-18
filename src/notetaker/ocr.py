"""Reading scanned PDFs by looking at them.

A scanned PDF has no text layer -- it is a picture of a page. The pages are
rendered to images here and handed to a local vision model, which keeps the
promise the rest of the tool makes: nothing leaves the machine.

This is off unless asked for, and that is deliberate. A vision model that
misreads a word does not produce obvious garbage the way a traditional OCR
engine does; it produces a plausible wrong word. Flashcards made from a
confident misreading are worse than no flashcards, because they teach the
mistake. So the user opts in, and the tool says what it is doing.
"""

from __future__ import annotations

import base64
import io
import re
from collections.abc import Callable
from pathlib import Path

DEFAULT_VISION_MODEL = "qwen2.5vl:3b"
DEFAULT_DPI = 150
"""Enough for body text. Higher mostly costs time and context."""

MAX_IMAGE_EDGE = 1400
"""Longest side handed to the model, in pixels.

A vision model turns an image into tokens, and the count climbs with area, so
a full-resolution page render costs a great deal of time for detail the model
cannot use. Anything larger than this is scaled down before it is sent.
"""

DEFAULT_TIMEOUT = 300.0
MAX_PAGES = 40

TRANSCRIBE_PROMPT = (
    "Transcribe every word of text in this image, exactly as written.\n"
    "\n"
    "- Put each heading on its own line.\n"
    "- Keep the blank line between paragraphs.\n"
    "- Do not summarize, correct, explain or translate anything.\n"
    "- Do not add any commentary before or after the transcription.\n"
    "- If the image has no readable text, reply with nothing at all."
)

FENCE_RE = re.compile(r"^```[a-z]*\n|\n```$", re.IGNORECASE)
PREAMBLE_RE = re.compile(
    r"^(here (is|are)|this (image|page) (shows|contains)|the (text|transcription))\b[^\n]*:\s*\n",
    re.IGNORECASE,
)


class OcrError(Exception):
    """The pages could not be read as images."""


def render_pdf_pages(
    path: Path,
    *,
    dpi: int = DEFAULT_DPI,
    max_pages: int = MAX_PAGES,
) -> list[bytes]:
    """Render each page of `path` to a PNG."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise OcrError("Reading scans needs extra packages: pip install 'notetaker[ocr]'") from exc

    try:
        document = pdfium.PdfDocument(str(path))
    except Exception as exc:
        raise OcrError(f"{path.name} could not be opened as a PDF: {exc}") from exc

    images: list[bytes] = []
    try:
        for index, page in enumerate(document):
            if index >= max_pages:
                break
            bitmap = page.render(scale=dpi / 72)
            buffer = io.BytesIO()
            _fit(bitmap.to_pil()).save(buffer, format="PNG")
            images.append(buffer.getvalue())
    finally:
        document.close()

    if not images:
        raise OcrError(f"{path.name} has no pages to read.")
    return images


def _fit(image):
    """Scale a page down to `MAX_IMAGE_EDGE` on its longest side, if it is bigger."""
    longest = max(image.size)
    if longest <= MAX_IMAGE_EDGE:
        return image

    ratio = MAX_IMAGE_EDGE / longest
    width = max(1, round(image.width * ratio))
    height = max(1, round(image.height * ratio))
    return image.resize((width, height))


def transcribe(
    image: bytes,
    *,
    model: str = DEFAULT_VISION_MODEL,
    host: str = "http://localhost:11434",
    timeout: float = DEFAULT_TIMEOUT,
    client=None,
) -> str:
    """Ask a local vision model what the page says."""
    import httpx

    owned = client is None
    http = client or httpx.Client(timeout=timeout)

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": TRANSCRIBE_PROMPT,
                "images": [base64.b64encode(image).decode("ascii")],
            }
        ],
        "stream": False,
        "options": {"temperature": 0, "seed": 7},
    }

    try:
        response = http.post(f"{host.rstrip('/')}/api/chat", json=payload)
    except httpx.TimeoutException as exc:
        raise OcrError(
            f"{model} took longer than {timeout:.0f}s on one page. Vision models are "
            "slow unless they fit in your GPU's memory -- check `ollama ps`, and if "
            "size_vram is 0 the model is running on the CPU. Try --ocr-dpi 100, or "
            "raise --ocr-timeout and expect to wait."
        ) from exc
    except httpx.ConnectError as exc:
        raise OcrError(f"Could not reach Ollama at {host}. Start it with `ollama serve`.") from exc
    except httpx.HTTPError as exc:
        raise OcrError(f"Request to Ollama failed: {exc}") from exc
    finally:
        if owned:
            http.close()

    if response.status_code == 404:
        raise OcrError(f"Ollama does not have {model!r}. Pull it with `ollama pull {model}`.")
    if response.status_code >= 400:
        raise OcrError(f"Ollama returned {response.status_code}: {response.text[:200]}")

    body = response.json()
    if "error" in body:
        raise OcrError(f"Ollama reported an error: {body['error']}")

    return tidy(body.get("message", {}).get("content", ""))


def read_pdf_with_ocr(
    path: Path,
    *,
    model: str = DEFAULT_VISION_MODEL,
    dpi: int = DEFAULT_DPI,
    host: str = "http://localhost:11434",
    timeout: float = DEFAULT_TIMEOUT,
    max_pages: int = MAX_PAGES,
    on_page: Callable[[int, int], None] | None = None,
    client=None,
) -> str:
    """Render every page and transcribe it. Slow by nature: one model call per page."""
    images = render_pdf_pages(path, dpi=dpi, max_pages=max_pages)

    pages: list[str] = []
    for number, image in enumerate(images, start=1):
        if on_page is not None:
            on_page(number, len(images))
        text = transcribe(image, model=model, host=host, timeout=timeout, client=client)
        if text.strip():
            pages.append(text.strip())

    if not pages:
        raise OcrError(
            f"{model} found no text in {path.name}. "
            "If the scan is faint or skewed, a clearer one will read better."
        )
    return "\n\n".join(pages)


def tidy(text: str) -> str:
    """Strip the wrappers a chat model puts around a transcription."""
    cleaned = FENCE_RE.sub("", text.strip())
    cleaned = PREAMBLE_RE.sub("", cleaned.strip())
    return cleaned.strip()
