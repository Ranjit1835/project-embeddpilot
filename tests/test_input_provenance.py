"""V1.6 Priority 1: no field is ever silently populated with an invented value.

Covers the four required cases plus a regression that reproduces the exact
reported bug (empty Interface + chip fields must NOT auto-fill and proceed).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generation.inputs import (
    InputProvenanceError,
    assert_input_provenance,
)
from generation.router import route
from generation.worker import build_worker_prompt
from ingestion.loader import Document, Page
from ingestion.pipeline import ingest_datasheet

CONFIRMED = {
    "chip": "BME280", "peripheral": "I2C",
    "provenance": {"chip": "user", "peripheral": "user"},
    "registers": [], "commands": [],
}


# --- the guard: block empty / unconfirmed / invented, allow user / detected ----

def test_empty_fields_are_blocked_by_named_field():
    m = {"chip": "", "peripheral": "", "provenance": {}}
    with pytest.raises(InputProvenanceError) as e:
        assert_input_provenance(m, "esp32")
    assert "Chip" in str(e.value) and "required" in str(e.value)


def test_empty_platform_is_blocked():
    with pytest.raises(InputProvenanceError) as e:
        assert_input_provenance(CONFIRMED, "")
    assert "platform" in str(e.value).lower()


def test_detected_but_unconfirmed_is_blocked():
    m = dict(CONFIRMED, provenance={"chip": "detected_unconfirmed", "peripheral": "user"})
    with pytest.raises(InputProvenanceError) as e:
        assert_input_provenance(m, "esp32")
    assert "not confirmed" in str(e.value)


def test_invented_value_unknown_provenance_is_blocked():
    # a value present with no legitimate origin — the invented-value path
    m = {"chip": "BME280", "peripheral": "I2C", "provenance": {}}
    with pytest.raises(InputProvenanceError) as e:
        assert_input_provenance(m, "esp32")
    assert "unknown provenance" in str(e.value)


def test_user_and_detected_confirmed_pass():
    assert_input_provenance(CONFIRMED, "esp32")  # no raise
    ok = dict(CONFIRMED, provenance={"chip": "detected", "peripheral": "detected"})
    assert_input_provenance(ok, "esp32")  # confirmed-detected is allowed


# --- prompt construction fails loudly on bad provenance (belt & suspenders) -----

def test_worker_prompt_construction_asserts_provenance():
    invented = {"chip": "BME280", "peripheral": "I2C", "provenance": {},
                "registers": [], "commands": []}
    d = route(invented, "stm32", log=False)
    with pytest.raises(InputProvenanceError):
        build_worker_prompt(invented, d, "stm32")


def test_worker_prompt_builds_for_confirmed_inputs():
    d = route(CONFIRMED, "stm32", log=False)
    p = build_worker_prompt(CONFIRMED, d, "stm32")
    assert "BME280" in p and "STM32" in p  # platform profile label surfaced


# --- REGRESSION: the exact reported bug -----------------------------------------

def test_regression_empty_fields_do_not_autofill_from_filename():
    """Reported bug: Interface + chip left empty -> system auto-filled random
    values (the filename) and proceeded. A datasheet with no detectable chip
    must leave chip empty (never the filename) and be blocked at generate time."""
    doc = Document(path="/tmp/9a3f_download.pdf", kind="pdf", pages=[
        Page(number=1, text="Generic component overview. No part number here."),
        Page(number=2, text="Electrical characteristics table follows."),
    ])
    # detection finds nothing -> chip/peripheral stay empty, provenance null
    from ingestion.detect import detect_metadata
    assert "chip" not in detect_metadata(doc)

    # and the guard blocks generation rather than proceeding on an invented value
    empty = {"chip": "", "peripheral": "", "provenance": {"chip": None, "peripheral": None}}
    with pytest.raises(InputProvenanceError):
        assert_input_provenance(empty, "esp32")


def test_regression_ingestion_never_fills_chip_from_filename(tmp_path):
    """Full pipeline: a real datasheet ingested with NO user-supplied chip must
    resolve chip from DETECTION (labeled detected_unconfirmed), never from the
    upload filename."""
    src = os.path.join(os.path.dirname(__file__), "..", "extraction", "input", "bmp180.pdf")
    if not os.path.exists(src):
        pytest.skip("bmp180.pdf not present")
    # copy under a random job-style filename to prove the name never leaks
    dst = tmp_path / "1b2c3d_download.pdf"
    dst.write_bytes(open(src, "rb").read())
    m = ingest_datasheet(str(dst), chip="", peripheral="", page_range=(1, 20))
    assert "1b2c3d" not in m["chip"] and "download" not in m["chip"].lower()
    assert m["chip"] == "BMP180"
    assert m["provenance"]["chip"] == "detected_unconfirmed"
