"""The web front end, driven with the offline backend so CI stays offline."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from notetaker.web.app import create_app

NOTES = b"""# Biology

Osmosis is the diffusion of water across a selectively permeable membrane.

Active transport is movement that requires energy supplied by ATP.
"""


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def start(client, name: str = "bio.md", body: bytes = NOTES, **fields) -> str:
    form = {"backend": "fake", "style": "basic"}
    form.update({key: str(value) for key, value in fields.items()})
    response = client.post("/api/jobs", files={"file": (name, body)}, data=form)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def finish(client, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("the job never finished")


def test_reasoning_models_are_flagged_as_slow(client, monkeypatch) -> None:
    import httpx

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "models": [
                    {"name": "llama3.2:latest"},
                    {"name": "qwen3.5:9b"},
                    {"name": "deepseek-r1:8b"},
                ]
            }

    monkeypatch.setattr(httpx, "get", lambda *a, **k: Response())

    models = {entry["name"]: entry["slow"] for entry in client.get("/api/models").json()["models"]}
    assert models == {"llama3.2:latest": False, "qwen3.5:9b": True, "deepseek-r1:8b": True}


def test_no_models_reported_when_ollama_is_down(client, monkeypatch) -> None:
    import httpx

    def refuse(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", refuse)

    body = client.get("/api/models").json()
    assert body["available"] is False
    assert body["models"] == []


def test_the_page_is_served(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "notetaker" in response.text
    assert "Drop notes here" in response.text


def test_the_page_makes_no_external_requests(client) -> None:
    # This tool's whole claim is that notes stay on the machine. A stylesheet
    # or font pulled from a CDN would quietly break that promise.
    page = client.get("/").text
    assert "http://" not in page.replace('http://" + ', "")
    assert "https://" not in page


def test_a_job_runs_and_produces_cards(client) -> None:
    job = finish(client, start(client))
    assert job["state"] == "done"
    assert job["cards"]
    assert any("Osmosis" in card["question"] for card in job["cards"])


def test_progress_reports_every_section(client) -> None:
    job = finish(client, start(client))
    assert job["total"] == job["done"]
    assert job["sections"]
    assert all("tag" in section and "cards" in section for section in job["sections"])


def test_both_downloads_are_available_when_done(client) -> None:
    job_id = start(client)
    finish(client, job_id)

    apkg = client.get(f"/api/jobs/{job_id}/deck.apkg")
    tsv = client.get(f"/api/jobs/{job_id}/deck.tsv")

    assert apkg.status_code == 200
    assert apkg.content[:2] == b"PK"
    assert tsv.status_code == 200
    assert "#notetype:Basic" in tsv.text


def test_the_cloze_style_is_honoured(client) -> None:
    job_id = start(client, style="cloze")
    job = finish(client, job_id)
    assert job["state"] == "done"
    assert "{{c1::" in job["cards"][0]["question"]
    assert "#notetype:Cloze" in client.get(f"/api/jobs/{job_id}/deck.tsv").text


def test_extra_tags_reach_the_cards(client) -> None:
    job = finish(client, start(client, tags="bio101 midterm"))
    assert "bio101" in job["cards"][0]["tags"]
    assert "midterm" in job["cards"][0]["tags"]


def test_the_deck_name_is_used(client) -> None:
    job_id = start(client, deck="Bio::Week 3")
    finish(client, job_id)
    assert client.get(f"/api/jobs/{job_id}/deck.apkg").status_code == 200


def test_a_pdf_can_be_uploaded(client, tmp_path: Path) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.multi_cell(0, 8, "Osmosis is the diffusion of water across a membrane.")
    path = tmp_path / "notes.pdf"
    pdf.output(str(path))

    job = finish(client, start(client, name="notes.pdf", body=path.read_bytes()))
    assert job["state"] == "done"
    assert job["cards"]


def test_an_unsupported_file_type_is_refused(client) -> None:
    response = client.post(
        "/api/jobs",
        files={"file": ("notes.docx", b"nope")},
        data={"backend": "fake"},
    )
    assert response.status_code == 400
    assert ".pdf" in response.json()["detail"]


def test_an_unknown_style_is_refused(client) -> None:
    response = client.post(
        "/api/jobs",
        files={"file": ("bio.md", NOTES)},
        data={"backend": "fake", "style": "reversed"},
    )
    assert response.status_code == 400


def test_notes_with_nothing_in_them_report_an_error(client) -> None:
    job = finish(client, start(client, body=b"   \n\n  \n"))
    assert job["state"] == "error"
    assert "no readable notes" in job["error"]


def test_downloads_are_refused_before_the_job_finishes(client) -> None:
    job = finish(client, start(client, body=b"   \n"))
    assert job["state"] == "error"
    response = client.get(f"/api/jobs/{job['id']}/deck.apkg")
    assert response.status_code == 409


def test_an_unknown_job_is_a_404(client) -> None:
    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_an_unknown_download_format_is_a_404(client) -> None:
    job_id = start(client)
    finish(client, job_id)
    assert client.get(f"/api/jobs/{job_id}/deck.exe").status_code == 404


def test_an_upload_cannot_escape_its_directory(client) -> None:
    # The filename comes from the browser and is not to be trusted.
    job = finish(client, start(client, name="../../escape.md"))
    assert job["name"] == "escape.md"
    assert job["state"] == "done"
