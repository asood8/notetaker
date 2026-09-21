"""The web front end, driven with the offline backend so CI stays offline."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from notetaker.web.app import create_app

NOTES = b"""# Biology

## Transport

Osmosis is the diffusion of water across a selectively permeable membrane.

## Energy

Active transport is movement that requires energy supplied by ATP.

## Respiration

Glycolysis is the breakdown of glucose into pyruvate.
"""


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def preview(client, name: str = "bio.md", body: bytes = NOTES, **fields) -> dict:
    response = client.post(
        "/api/preview",
        files={"file": (name, body)},
        data={key: str(value) for key, value in fields.items()},
    )
    assert response.status_code == 200, response.text
    return response.json()


def start(client, preview_id: str, **fields) -> str:
    form = {"preview_id": preview_id, "backend": "fake", "style": "basic"}
    form.update({key: str(value) for key, value in fields.items()})
    response = client.post("/api/jobs", data=form)
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


def run(client, **fields) -> dict:
    return finish(client, start(client, preview(client)["id"], **fields))


# --- the page ----------------------------------------------------------------


def test_the_page_is_served(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Drop notes here" in response.text


def test_the_page_makes_no_external_requests(client) -> None:
    # This tool's whole claim is that notes stay on the machine. A stylesheet
    # or font pulled from a CDN would quietly break that promise.
    page = client.get("/").text
    assert "https://" not in page
    assert "http://" not in page.replace('"http://localhost', "")


def test_the_page_offers_every_option_the_cli_has(client) -> None:
    page = client.get("/").text
    for control in ("style", "model", "deck", "tags", "max_cards", "check", "first", "last"):
        assert f'id="{control}"' in page


# --- models ------------------------------------------------------------------


def test_reasoning_models_are_flagged_as_slow(client, monkeypatch) -> None:
    import httpx

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"models": [{"name": "llama3.2:latest"}, {"name": "qwen3.5:9b"}]}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: Response())
    models = {entry["name"]: entry["slow"] for entry in client.get("/api/models").json()["models"]}
    assert models == {"llama3.2:latest": False, "qwen3.5:9b": True}


def test_no_models_reported_when_ollama_is_down(client, monkeypatch) -> None:
    import httpx

    def refuse(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", refuse)
    body = client.get("/api/models").json()
    assert body["available"] is False


# --- previewing --------------------------------------------------------------


def test_a_preview_lists_the_sections(client) -> None:
    body = preview(client)
    assert body["total"] == 3
    assert [section["tag"] for section in body["sections"]] == [
        "Biology::Transport",
        "Biology::Energy",
        "Biology::Respiration",
    ]


def test_a_preview_estimates_the_work(client) -> None:
    body = preview(client)
    assert "to" in body["estimate"]
    assert body["estimate"] != body["estimate_checked"]
    assert body["seconds_per_section"] == [15, 35]


def test_a_preview_calls_no_model(client) -> None:
    # Nothing here needs Ollama, which is why the page can show it instantly.
    body = preview(client)
    assert body["sections"]
    assert "cards" not in body


def test_section_size_can_be_changed_without_uploading_again(client) -> None:
    body = preview(client)
    response = client.post(f"/api/preview/{body['id']}/resplit", data={"chunk_chars": "500"})
    assert response.status_code == 200
    assert response.json()["id"] == body["id"]


def test_an_unsupported_file_type_is_refused(client) -> None:
    response = client.post("/api/preview", files={"file": ("notes.docx", b"nope")})
    assert response.status_code == 400
    assert ".pdf" in response.json()["detail"]


def test_a_file_with_nothing_in_it_is_refused(client) -> None:
    response = client.post("/api/preview", files={"file": ("empty.md", b"   \n\n ")})
    assert response.status_code == 400


def test_a_scan_is_offered_ocr_rather_than_refused(client, tmp_path: Path) -> None:
    from test_ocr import make_scan

    scan = make_scan(tmp_path / "scan.pdf")
    body = preview(client, name="scan.pdf", body=scan.read_bytes())

    assert body["needs_ocr"] is True
    assert "scan" in body["message"]


def test_a_pdf_can_be_previewed(client, tmp_path: Path) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.multi_cell(0, 8, "Osmosis is the diffusion of water across a membrane.")
    path = tmp_path / "notes.pdf"
    pdf.output(str(path))

    assert preview(client, name="notes.pdf", body=path.read_bytes())["total"] >= 1


# --- generating --------------------------------------------------------------


def test_a_job_produces_cards(client) -> None:
    job = run(client)
    assert job["state"] == "done"
    assert any("Osmosis" in card["question"] for card in job["cards"])


def test_progress_reports_every_section(client) -> None:
    job = run(client)
    assert job["total"] == job["done"] == 3


def test_only_the_chosen_sections_are_used(client) -> None:
    job = finish(client, start(client, preview(client)["id"], first=2, last=3))
    assert job["total"] == 2
    assert job["first"] == 2
    assert job["last"] == 3
    assert not any("Osmosis" in card["question"] for card in job["cards"])


def test_a_single_section_can_be_chosen(client) -> None:
    job = finish(client, start(client, preview(client)["id"], first=1, last=1))
    assert job["total"] == 1


def test_extra_tags_reach_the_cards(client) -> None:
    job = run(client, tags="bio101 midterm")
    assert "bio101" in job["cards"][0]["tags"]


def test_the_cloze_style_is_honoured(client) -> None:
    job = run(client, style="cloze")
    assert "{{c1::" in job["cards"][0]["question"]


def test_the_checker_can_be_turned_on(client) -> None:
    job = run(client, check="true")
    assert job["state"] == "done"
    assert "unsupported" in job["counts"]


def test_an_unknown_style_is_refused(client) -> None:
    body = preview(client)
    response = client.post(
        "/api/jobs", data={"preview_id": body["id"], "backend": "fake", "style": "reversed"}
    )
    assert response.status_code == 400


def test_an_unknown_file_is_a_404(client) -> None:
    response = client.post("/api/jobs", data={"preview_id": "nope", "backend": "fake"})
    assert response.status_code == 404


# --- results -----------------------------------------------------------------


def test_both_downloads_are_available_when_done(client) -> None:
    job_id = start(client, preview(client)["id"])
    finish(client, job_id)

    apkg = client.get(f"/api/jobs/{job_id}/deck.apkg")
    tsv = client.get(f"/api/jobs/{job_id}/deck.tsv")

    assert apkg.content[:2] == b"PK"
    assert "#notetype:Basic" in tsv.text


def test_a_ranged_run_names_its_files_after_the_range(client) -> None:
    job_id = start(client, preview(client)["id"], first=2, last=3)
    finish(client, job_id)
    response = client.get(f"/api/jobs/{job_id}/deck.apkg")
    assert "2-3" in response.headers["content-disposition"]


def test_rejected_cards_come_back_with_a_reason(client) -> None:
    # A duplicate is the one rejection the offline matcher reliably produces:
    # the same sentence in two sections yields the same card twice.
    repeated = NOTES + b"\n## Again\n\nOsmosis is the diffusion of water across a membrane.\n"
    job = finish(client, start(client, preview(client, body=repeated)["id"]))

    assert job["rejected"], "expected the repeated card to be dropped"
    assert all(item["reason"] for item in job["rejected"])


def test_the_dropped_file_is_offered_only_when_there_is_one(client) -> None:
    job_id = start(client, preview(client)["id"])
    job = finish(client, job_id)
    response = client.get(f"/api/jobs/{job_id}/deck.dropped.tsv")
    expected = 200 if job["rejected"] else 404
    assert response.status_code == expected


def test_an_unknown_download_format_is_a_404(client) -> None:
    job_id = start(client, preview(client)["id"])
    finish(client, job_id)
    assert client.get(f"/api/jobs/{job_id}/deck.exe").status_code == 404


def test_an_unknown_job_is_a_404(client) -> None:
    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_an_upload_cannot_escape_its_directory(client) -> None:
    # The filename comes from the browser and is not to be trusted.
    assert preview(client, name="../../escape.md")["name"] == "escape.md"


# --- choosing which cards to keep --------------------------------------------


def test_only_the_ticked_cards_are_downloaded(client) -> None:
    job_id = start(client, preview(client)["id"])
    job = finish(client, job_id)
    assert len(job["cards"]) > 1

    full = client.get(f"/api/jobs/{job_id}/deck.tsv").text
    one = client.get(f"/api/jobs/{job_id}/deck.tsv?keep=0").text

    assert len(one.splitlines()) < len(full.splitlines())
    assert job["cards"][0]["question"] in one


def test_a_selected_deck_is_still_a_valid_package(client) -> None:
    job_id = start(client, preview(client)["id"])
    finish(client, job_id)
    response = client.get(f"/api/jobs/{job_id}/deck.apkg?keep=0")
    assert response.content[:2] == b"PK"


def test_selecting_nothing_is_refused(client) -> None:
    job_id = start(client, preview(client)["id"])
    finish(client, job_id)
    assert client.get(f"/api/jobs/{job_id}/deck.tsv?keep=").status_code == 400


def test_nonsense_indices_are_ignored(client) -> None:
    job_id = start(client, preview(client)["id"])
    finish(client, job_id)
    response = client.get(f"/api/jobs/{job_id}/deck.tsv?keep=0,999,abc")
    assert response.status_code == 200
    assert len(response.text.splitlines()) == 5


def test_the_page_lets_you_untick_a_card(client) -> None:
    page = client.get("/").text
    assert 'id="pick-all"' in page
    assert "Untick any card" in page
