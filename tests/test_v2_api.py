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

    r = client.post("/api/v2/build", json={
        "requirement": REQ,
        "register_map": {"chip": "MYSTERY",
                         "registers": [{"name": "cfg", "offset": "0x01"}]},
        "address": "0x40"})
    job_id = r.json()["job_id"]
    for _ in range(50):
        snap = client.get(f"/api/jobs/{job_id}").json()
        if snap.get("status") in ("done", "error"):
            break
        time.sleep(0.1)
    result = snap.get("result") or {}
    assert result.get("status") == "blocked-no-read-plan"
    assert result.get("notes"), "must say WHY it refused"
