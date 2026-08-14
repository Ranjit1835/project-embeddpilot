"""V1.9 item 3: fixed-readout device (TMP125) — extraction, grounded generation,
the readout cross-check (hard-fail on mismatch), the block condition, and scope.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generation.inputs import InputProvenanceError
from generation.pipeline import generate_validated_driver
from generation.provider import MockProvider
from generation.router import route
from generation.worker import generate_driver
from validator.readout_crosscheck import readout_crosscheck
from validator.report import ValidationReport
from validator.scope import build_scope

READOUT = {"bit_width": 16, "value_msb": 14, "value_lsb": 5, "signed": True,
           "lsb_weight": 0.25, "unit": "°C"}
READOUT_MAP = {
    "chip": "TMP125", "peripheral": "SPI",
    "provenance": {"chip": "user", "peripheral": "user"},
    "base_address": None, "registers": [], "commands": [], "readout": READOUT,
}

HEADER = (
    "#pragma once\n#include <Arduino.h>\n#include <SPI.h>\n#include <stdint.h>\n"
    "#define TMP125_WORD_BITS 16\n#define TMP125_VALUE_MSB 14\n"
    "#define TMP125_VALUE_LSB 5\n#define TMP125_SIGNED 1\n"
    "#define TMP125_LSB_WEIGHT 0.25f\n"
    "class TMP125 {\npublic:\n  TMP125(SPIClass &bus = SPI, uint8_t cs = 10);\n"
    "  bool begin();\n  bool readTemperature(float &t);\n};\n"
)
READOUT_LIB = {
    "header_cpp": HEADER,
    "source_cpp": '#include "TMP125.h"\nTMP125::TMP125(SPIClass &, uint8_t) {}\n'
                  "bool TMP125::begin() { return true; }\n"
                  "bool TMP125::readTemperature(float &t) { t = 0; return true; }\n",
    "example_ino": "#include <TMP125.h>\nTMP125 s;\nvoid setup() {}\nvoid loop() {}\n",
    "readme_md": "# TMP125\n",
}


def _files(header: str) -> dict:
    return {"TMP125/src/TMP125.h": header.splitlines()}


# --- extraction ---

def test_extract_readout_from_tmp125_datasheet():
    path = os.path.join(os.path.dirname(__file__), "..", "extraction", "input", "tmp125.pdf")
    if not os.path.exists(path):
        pytest.skip("tmp125.pdf not present")
    from ingestion.loader import load_document
    from ingestion.readout import extract_readout
    r = extract_readout(load_document(path))
    assert r == {**{"bit_width": 16, "value_msb": 14, "value_lsb": 5, "signed": True,
                    "lsb_weight": 0.25, "unit": "°C"},
                 "source_pages": [5], "confidence": "high"}


# --- grounded generation shape ---

def test_readout_worker_emits_named_parameter_defines():
    dec = route(READOUT_MAP, "arduino", log=False)
    res = generate_driver(MockProvider([READOUT_LIB]), READOUT_MAP, dec, "arduino",
                          target="arduino")
    h = res.files["TMP125/src/TMP125.h"]
    for d in ("TMP125_WORD_BITS", "TMP125_VALUE_MSB", "TMP125_VALUE_LSB",
              "TMP125_SIGNED", "TMP125_LSB_WEIGHT"):
        assert d in h


# --- the readout cross-check is the grounding: hard-fail on mismatch ---

def test_readout_crosscheck_passes_when_defines_match():
    r = ValidationReport()
    readout_crosscheck(_files(HEADER), READOUT, r)
    assert r.checks["readout_crosscheck"] == "pass"
    assert not r.failures


def test_readout_crosscheck_hard_fails_on_wrong_scale():
    bad = HEADER.replace("#define TMP125_LSB_WEIGHT 0.25f",
                         "#define TMP125_LSB_WEIGHT 0.5f")
    r = ValidationReport()
    readout_crosscheck(_files(bad), READOUT, r)
    assert r.checks["readout_crosscheck"] == "fail"
    assert any("LSB weight" in f.message for f in r.failures)


def test_readout_crosscheck_hard_fails_on_missing_parameter():
    bad = HEADER.replace("#define TMP125_VALUE_LSB 5\n", "")
    r = ValidationReport()
    readout_crosscheck(_files(bad), READOUT, r)
    assert r.checks["readout_crosscheck"] == "fail"


def test_finalize_readout_crosscheck_is_the_grounding():
    r = ValidationReport()
    r.checks = {"readout_crosscheck": "pass", "compile": "pass"}
    r.finalize()
    assert r.status == "validated"
    # without the readout grounding, not validated
    r2 = ValidationReport()
    r2.checks = {"compile": "pass"}
    r2.finalize()
    assert r2.status == "failed"


# --- required block condition ---

def test_register_less_no_readout_device_is_blocked():
    blank = {"chip": "MYST", "peripheral": "SPI",
             "provenance": {"chip": "user", "peripheral": "user"},
             "registers": [], "commands": []}
    with pytest.raises(InputProvenanceError):
        generate_validated_driver(blank, "arduino", MockProvider([]), target="arduino")


# --- scope panel ---

def test_scope_readout_says_no_register_map_fixed_readout():
    r = ValidationReport()
    r.checks = {"readout_crosscheck": "pass", "compile": "pass"}
    scope = {s["item"]: s for s in build_scope("arduino", READOUT_MAP, r, False)}
    assert scope[2]["status"] == "cross-checked"
    assert "fixed readout" in scope[2]["detail"].lower()
