"""Reading scans.

The fixtures here build a PDF that really is a picture of a page: text is
drawn into an image, and the image is placed on an otherwise empty page. That
makes these tests exercise the same path a phone-scanned handout takes,
including the check that there is no text layer to read.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

from notetaker.ocr import (
    OcrError,
    read_pdf_with_ocr,
    render_pdf_pages,
    tidy,
    transcribe,
)
from notetaker.reader import UnreadableNotes, read_notes

LINES = [
    "Transport",
    "",
    "Osmosis is the diffusion of water across a",
    "selectively permeable membrane.",
]


def font():
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, 40)
        except OSError:
            continue
    return ImageFont.load_default()


def make_scan(path: Path, pages: int = 1, lines: list[str] | None = None) -> Path:
    """A PDF containing only images of text, with no text layer at all."""
    pdf = FPDF()
    face = font()

    for index in range(pages):
        image = Image.new("RGB", (1240, 1754), "white")
        draw = ImageDraw.Draw(image)
        y = 120
        for line in lines or LINES:
            draw.text((100, y), line, fill="black", font=face)
            y += 70

        page_image = path.parent / f"_page{index}.png"
        image.save(page_image)
        pdf.add_page()
        pdf.image(str(page_image), x=10, y=10, w=190)

    pdf.output(str(path))
    return path


def chat(content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


def client_returning(*responses: httpx.Response, record: list | None = None) -> httpx.Client:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if record is not None:
            record.append(json.loads(request.content))
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return httpx.Client(transport=httpx.MockTransport(handler))


# --- the fixture really is a scan ---------------------------------------------


def test_a_scanned_pdf_has_no_text_layer(tmp_path: Path) -> None:
    scan = make_scan(tmp_path / "scan.pdf")
    with pytest.raises(UnreadableNotes, match="probably a scan"):
        read_notes(scan)


def test_the_error_points_at_the_ocr_flag(tmp_path: Path) -> None:
    scan = make_scan(tmp_path / "scan.pdf")
    with pytest.raises(UnreadableNotes, match=r"--ocr"):
        read_notes(scan)


# --- rendering ----------------------------------------------------------------


def test_every_page_is_rendered_to_a_png(tmp_path: Path) -> None:
    scan = make_scan(tmp_path / "scan.pdf", pages=3)
    images = render_pdf_pages(scan)
    assert len(images) == 3
    assert all(image.startswith(b"\x89PNG") for image in images)


def test_rendering_respects_the_page_limit(tmp_path: Path) -> None:
    scan = make_scan(tmp_path / "scan.pdf", pages=4)
    assert len(render_pdf_pages(scan, max_pages=2)) == 2


def test_a_higher_dpi_makes_a_bigger_image(tmp_path: Path) -> None:
    scan = make_scan(tmp_path / "scan.pdf")
    assert len(render_pdf_pages(scan, dpi=300)[0]) > len(render_pdf_pages(scan, dpi=72)[0])


def test_a_file_that_is_not_a_pdf_is_reported(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    with pytest.raises(OcrError, match="could not be opened"):
        render_pdf_pages(broken)


# --- talking to the vision model ----------------------------------------------


def test_the_image_is_sent_as_base64(tmp_path: Path) -> None:
    sent: list = []
    http = client_returning(chat("Transport"), record=sent)
    transcribe(b"\x89PNG fake", model="qwen2.5vl:3b", client=http)

    message = sent[0]["messages"][0]
    assert message["images"]
    assert sent[0]["options"]["temperature"] == 0
    # A schema would be wrong here: the answer is prose, not a card.
    assert "format" not in sent[0]


def test_the_transcription_comes_back(tmp_path: Path) -> None:
    http = client_returning(chat("Osmosis is the diffusion of water."))
    assert transcribe(b"png", client=http) == "Osmosis is the diffusion of water."


def test_a_missing_vision_model_names_the_pull_command() -> None:
    http = client_returning(httpx.Response(404, json={"error": "not found"}))
    with pytest.raises(OcrError, match="ollama pull qwen2.5vl:3b"):
        transcribe(b"png", client=http)


def test_a_refused_connection_says_how_to_start_ollama() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(OcrError, match="ollama serve"):
        transcribe(b"png", client=http)


def test_a_timeout_is_reported_per_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(OcrError, match="on one page"):
        transcribe(b"png", client=http, timeout=5)


def test_an_error_field_is_surfaced() -> None:
    http = client_returning(httpx.Response(200, json={"error": "out of memory"}))
    with pytest.raises(OcrError, match="out of memory"):
        transcribe(b"png", client=http)


# --- tidying what a chat model wraps around a transcription --------------------


def test_a_code_fence_is_stripped() -> None:
    assert tidy("```\nOsmosis is diffusion.\n```") == "Osmosis is diffusion."


def test_a_preamble_is_stripped() -> None:
    assert tidy("Here is the transcription:\nOsmosis is diffusion.") == "Osmosis is diffusion."


def test_plain_text_is_left_alone() -> None:
    assert tidy("Osmosis is diffusion.") == "Osmosis is diffusion."


def test_a_colon_inside_real_notes_is_not_mistaken_for_a_preamble() -> None:
    text = "Osmosis: the diffusion of water.\nActive transport needs ATP."
    assert tidy(text) == text


# --- the whole scan path ------------------------------------------------------


def test_pages_are_joined_in_order(tmp_path: Path) -> None:
    scan = make_scan(tmp_path / "scan.pdf", pages=2)
    http = client_returning(chat("First page."), chat("Second page."))
    text = read_pdf_with_ocr(scan, client=http)
    assert text == "First page.\n\nSecond page."


def test_progress_is_reported_per_page(tmp_path: Path) -> None:
    scan = make_scan(tmp_path / "scan.pdf", pages=3)
    seen: list[tuple[int, int]] = []
    read_pdf_with_ocr(
        scan,
        client=client_returning(chat("text")),
        on_page=lambda number, total: seen.append((number, total)),
    )
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_a_scan_the_model_cannot_read_is_an_error(tmp_path: Path) -> None:
    scan = make_scan(tmp_path / "scan.pdf")
    with pytest.raises(OcrError, match="found no text"):
        read_pdf_with_ocr(scan, client=client_returning(chat("")))


def test_reading_a_scan_through_the_reader(tmp_path: Path) -> None:
    scan = make_scan(tmp_path / "scan.pdf")
    http = client_returning(chat("Transport\n\nOsmosis is the diffusion of water."))

    text = read_notes(scan, ocr=lambda path: read_pdf_with_ocr(path, client=http))

    # The transcription goes through the same cleanup a text layer does, so a
    # heading above prose still becomes a heading.
    assert text.startswith("## Transport")
    assert "Osmosis is the diffusion of water." in text


# --- keeping pages small enough to be worth sending ---------------------------


def test_a_large_page_is_scaled_to_the_limit(tmp_path: Path) -> None:
    import io

    from notetaker.ocr import MAX_IMAGE_EDGE

    scan = make_scan(tmp_path / "scan.pdf")
    image = Image.open(io.BytesIO(render_pdf_pages(scan, dpi=400)[0]))
    assert max(image.size) == MAX_IMAGE_EDGE


def test_scaling_keeps_the_shape_of_the_page(tmp_path: Path) -> None:
    import io

    scan = make_scan(tmp_path / "scan.pdf")
    raw = Image.open(io.BytesIO(render_pdf_pages(scan, dpi=72)[0]))
    scaled = Image.open(io.BytesIO(render_pdf_pages(scan, dpi=400)[0]))
    assert abs(raw.width / raw.height - scaled.width / scaled.height) < 0.01


def test_a_small_page_is_left_alone(tmp_path: Path) -> None:
    import io

    from notetaker.ocr import MAX_IMAGE_EDGE

    scan = make_scan(tmp_path / "scan.pdf")
    image = Image.open(io.BytesIO(render_pdf_pages(scan, dpi=72)[0]))
    assert max(image.size) < MAX_IMAGE_EDGE
