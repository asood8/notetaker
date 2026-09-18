"""OCR against a real vision model.

Excluded from the default run. These need a machine where the vision model
fits in GPU memory; on CPU a single page takes many minutes.

    pytest -m integration
"""

from pathlib import Path

import pytest

from notetaker.ocr import DEFAULT_VISION_MODEL, read_pdf_with_ocr

pytestmark = pytest.mark.integration


def test_a_scan_is_transcribed(tmp_path: Path) -> None:
    from test_ocr import make_scan

    scan = make_scan(
        tmp_path / "scan.pdf",
        lines=["Glycolysis occurs in the cytoplasm."],
    )

    text = read_pdf_with_ocr(scan, model=DEFAULT_VISION_MODEL, timeout=900)

    lowered = text.lower()
    assert "glycolysis" in lowered
    assert "cytoplasm" in lowered
