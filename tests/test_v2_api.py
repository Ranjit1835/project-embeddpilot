"""V2 API: the pipeline reachable from the product.

Uses MockProvider throughout — these tests must not need a network or a key, and
the refusals they assert are exactly the ones a real caller must not be able to
skip past.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import api.main as apimain  # noqa: E402
from generation.provider import MockProvider  # noqa: E402

REQ = ("Read the BMP180 over I2C at address 0x77 and print the raw temperature "
       "over UART.")

# the answers a user would give to the clarify loop, so a test can get PAST the
# gate and exercise a later stage
COMPLETE_ANSWERS = {
    "q:target.board": "Nucleo-F411RE",
    "q:target.mcu": "STM32F411RET6",
    "q:behaviors": "read temperature and print it over UART",
    "q:failure_behavior": "retry",
    "q:output_target": "cmake-project",
    "q:behaviors[0].trigger.source": "temperature",
    "q:behaviors[0].trigger.comparator": ">",
    "q:behaviors[0].trigger.threshold": "30 C",
    "q:constraints.sample_rate": "500 ms",
}


@pytest.fixture
def client(monkeypatch):
    """Every provider lookup in the API returns a deterministic mock."""
    def _mock():
        return MockProvider([{"devices": [{
            "name": {"value": "BMP180", "evidence": "BMP180"},
            "interface": {"value": "I2C", "evidence": "over I2C"},
            "address": {"value": "0x77", "evidence": "address 0x77"},
            "role": {"value": "temperature", "evidence": "raw temperature"},
        }]}] + [{} for _ in range(9)])

    monkeypatch.setattr("generation.provider.make_provider", _mock)
    return TestClient(apimain.app)


def test_analyze_requires_a_requirement(client):
    assert client.post("/api/v2/analyze", json={}).status_code == 422


def test_analyze_returns_questions_and_invents_nothing(client):
    """The product must surface the clarifying questions rather than proceeding
    on a spec it filled in itself."""
    r = client.post("/api/v2/analyze", json={"requirement": REQ})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "needs-clarification"
    assert body["questions"], "ambiguity must reach the user as questions"
    q = body["questions"][0]
    assert {"id", "field", "text", "blocking"} <= set(q)
    # a blocking question must be marked as such — the UI decides what to gate on
    assert any(x["blocking"] for x in body["questions"])


def test_analyze_surfaces_resource_state_once_the_spec_is_complete(client):
    answers = {
        "q:target.board": "Nucleo-F411RE",
        "q:target.mcu": "STM32F411RET6",
        "q:behaviors": "read temperature and print it over UART",
        "q:failure_behavior": "retry",
        "q:output_target": "cmake-project",
        "q:behaviors[0].trigger.source": "temperature",
        "q:behaviors[0].trigger.comparator": ">",
        "q:behaviors[0].trigger.threshold": "30 C",
        "q:constraints.sample_rate": "500 ms",
    }
    r = client.post("/api/v2/analyze",
                    json={"requirement": REQ, "answers": answers})
    body = r.json()
    assert body["status"] != "needs-clarification", body["questions"]
    assert body["devices"], "composed devices feed the Resource Map"
    assert "resource_crosscheck" in body["checks"]
    stages = {s["stage"] for s in body["stages"]}
    assert {"spec", "compose", "resource"} <= stages


def test_build_requires_a_requirement(client):
    assert client.post("/api/v2/build", json={}).status_code == 422


def test_build_returns_a_job(client):
    r = client.post("/api/v2/build", json={"requirement": REQ})
    assert r.status_code == 200
    assert "job_id" in r.json()


def test_build_refuses_a_map_with_nothing_readable(client):
    """A register map naming no data register must stop the build with a reason
    — never a guessed address."""
    import time

    # a COMPLETE spec, so the run gets past the clarify gate and actually reaches
    # read-plan derivation — the thing under test here
    r = client.post("/api/v2/build", json={
        "requirement": REQ,
        "answers": COMPLETE_ANSWERS,
        "register_map": {"chip": "BMP180",
                         "registers": [{"name": "cfg", "offset": "0x01"}]}})
    job_id = r.json()["job_id"]
    for _ in range(50):
        snap = client.get(f"/api/jobs/{job_id}").json()
        if snap.get("status") in ("done", "error"):
            break
        time.sleep(0.1)
    result = snap.get("result") or {}
    # The refusal is asserted by its PROPERTIES, not by one status string: the
    # derivation moved into the pipeline, so the shape changed while the promise
    # did not. What must hold is that nothing was generated and the reason is
    # stated — never a guessed register address.
    assert result.get("firmware_origin") is None, "nothing may be generated"
    assert result.get("status") != "working-emulated"
    generate = [s for s in result.get("stages", []) if s["stage"] == "generate"]
    reasons = " ".join(
        [s.get("detail", "") for s in generate]
        + list(result.get("derivation_notes", []))
        + list(result.get("notes", [])))
    assert "no data/output register" in reasons or "refusing" in reasons, reasons


# --- capabilities: what this deployment can actually do ---------------------

def test_capabilities_reports_toolchain_and_consequences(client):
    """A missing tool must be legible BEFORE a run. 'emulation skipped' means
    something very different when you can see the box has no Renode."""
    body = client.get("/api/v2/capabilities").json()
    assert set(body["toolchain"]) >= {"arm_none_eabi_gcc", "renode"}
    for name, tool in body["toolchain"].items():
        assert isinstance(tool["available"], bool)
        # every tool must say what its absence COSTS, or the panel is just a
        # row of red crosses the user cannot act on
        assert name in body["consequences"] and body["consequences"][name]


def test_capabilities_does_not_leak_the_api_key(client):
    """The endpoint reports which provider is configured. It must never echo the
    credential — this is the one place it would be easy to."""
    import json
    import os

    raw = json.dumps(client.get("/api/v2/capabilities").json())
    for var in ("GEMINI_API_KEY", "NVIDIA_API_KEY", "GROQ_API_KEY"):
        secret = os.environ.get(var)
        if secret:
            assert secret not in raw, f"{var} leaked into /api/v2/capabilities"
    assert "api_key" not in raw.lower()


def test_capabilities_states_what_is_not_built(client):
    """The same honesty the verdicts carry, applied to the feature list."""
    body = client.get("/api/v2/capabilities").json()
    joined = " ".join(body["not_built"]).lower()
    assert "hardware" in joined      # flashing / dump prediction are not built
    assert body["buses_supported"] == ["I2C", "SPI"]


# --- the generated repo must be visible, not just verdicts about it ---------

def test_build_result_carries_the_generated_files(client, monkeypatch):
    """The product's claim is a complete REPO. A run that reports 'working' and
    shows you nothing is a verdict about an artifact you cannot inspect."""
    import time

    captured = {}

    def fake_pipeline(*a, **kw):
        captured["called"] = True
        return {"status": "working-emulated", "stages": [],
                "devices": [], "firmware_origin": "generated",
                "verdict_note": "emulated only",
                "files": {"src/main.c": "int main(void){return 0;}",
                          "Makefile": "all:\n", "README.md": "# app\n"},
                "report": None, "questions": [], "spec": None}

    monkeypatch.setattr("orchestration.v2_pipeline.run_application_pipeline",
                        fake_pipeline)
    r = client.post("/api/v2/build", json={"requirement": REQ,
                                           "answers": COMPLETE_ANSWERS})
    jid = r.json()["job_id"]
    for _ in range(50):
        snap = client.get(f"/api/jobs/{jid}").json()
        if snap.get("status") in ("done", "error"):
            break
        time.sleep(0.1)
    files = (snap.get("result") or {}).get("files") or {}
    assert "src/main.c" in files and "Makefile" in files


def test_repo_zip_is_offered_and_refuses_when_there_is_nothing(client):
    """A blocked run has no repo; saying so is better than an empty zip that
    looks like output."""
    r = client.post("/api/v2/build", json={"requirement": REQ})
    jid = r.json()["job_id"]
    import time
    for _ in range(40):
        if client.get(f"/api/jobs/{jid}").json().get("status") in ("done", "error"):
            break
        time.sleep(0.1)
    z = client.get(f"/api/v2/jobs/{jid}/repo.zip")
    assert z.status_code == 404
    assert "nothing to download" in z.text or "no repo" in z.text
    assert client.get("/api/v2/jobs/does-not-exist/repo.zip").status_code == 404


# --- a requirement can arrive as a document, not only as typed text ---------

def test_requirement_from_a_text_file(client):
    text = ("On a Nucleo-F411RE with an STM32F411RET6, read the BMP180 over "
            "I2C at address 0x77 and print the raw temperature over UART.")
    r = client.post("/api/v2/requirement-from-file",
                    files={"file": ("req.txt", text.encode(), "text/plain")})
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == text
    # extraction is lossy and a requirement the user never saw is one they
    # cannot correct — the caller must confirm what we read
    assert body["review_required"] is True


def test_image_requirement_is_refused_honestly(client):
    """Not silently ignored and not fabricated: images need a vision model and
    that path is not wired, so say which and offer the alternative."""
    r = client.post("/api/v2/requirement-from-file",
                    files={"file": ("spec.png", b"\x89PNG\r\n", "image/png")})
    assert r.status_code == 415
    assert "vision-capable" in r.text and "PDF" in r.text


def test_unreadable_type_is_refused_with_the_supported_list(client):
    r = client.post("/api/v2/requirement-from-file",
                    files={"file": ("a.zip", b"PK\x03\x04", "application/zip")})
    assert r.status_code == 415
    assert ".pdf" in r.text and ".docx" in r.text
