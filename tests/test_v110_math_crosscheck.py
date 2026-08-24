"""V1.10a: math cross-check — extraction, execution, and the promotion rule.

Execution tests need a host compiler (gcc/cc/clang, or the bundled TinyCC). They
skip cleanly when none is present — exactly how the check degrades in production.
Extraction tests need the datasheet PDFs (gitignored) and skip when absent.
"""

from __future__ import annotations

import os

import pytest

from ingestion.math_oracle import (
    extract_conversion_table,
    extract_math_oracle,
    extract_reference_code,
)
from validator.crosscheck import COMPUTATION_MARKER, scan_unverified_computations
from validator.math_crosscheck import find_host_runner, math_crosscheck
from validator.report import UnverifiedComputation, UnverifiedField, ValidationReport

INPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "extraction", "input")
HAS_CC = find_host_runner() is not None
needs_cc = pytest.mark.skipif(not HAS_CC, reason="no host compiler to execute math")


def _pdf(name: str):
    from ingestion.loader import load_document
    path = os.path.join(INPUT_DIR, name)
    if not os.path.exists(path):
        pytest.skip(f"{name} not present")
    return load_document(path)


# --- fixtures: hand-written "generated" drivers -----------------------------

_LM_HDR = ["#include <stdint.h>", "float lm75b_raw_to_celsius(int32_t code);"]
_LM_GOOD = [
    '#include "lm75b_driver.h"',
    "float lm75b_raw_to_celsius(int32_t code){",
    "  int32_t s = code & 0x1FF;",
    "  if (s & 0x100) s -= 0x200;",   # 9-bit two's-complement sign extend
    "  return s * 0.5f;",
    "}",
]
_LM_ORACLE = {
    "kind": "table", "entry": "lm75b_raw_to_celsius", "input_ctype": "int32_t",
    "output_ctype": "float", "tolerance": "exact", "provenance": "detected",
    "source_pages": [14],
    "vectors": [{"in": 250, "out": 125.0}, {"in": 50, "out": 25.0},
                {"in": 1, "out": 0.5}, {"in": 0, "out": 0.0},
                {"in": 511, "out": -0.5}, {"in": 462, "out": -25.0},
                {"in": 402, "out": -55.0}],
}

_BME_REF = (
    "typedef int32_t BME280_S32_t;\n"
    "extern BME280_S32_t t_fine;\n"
    "BME280_S32_t BME280_compensate_T_int32(BME280_S32_t adc_T){\n"
    "  BME280_S32_t var1, var2, T;\n"
    "  var1 = ((((adc_T>>3) - ((BME280_S32_t)dig_T1<<1))) * ((BME280_S32_t)dig_T2)) >> 11;\n"
    "  var2 = (((((adc_T>>4) - ((BME280_S32_t)dig_T1)) * ((adc_T>>4) - ((BME280_S32_t)dig_T1))) >> 12) * ((BME280_S32_t)dig_T3)) >> 14;\n"
    "  t_fine = var1 + var2;\n"
    "  T = (t_fine * 5 + 128) >> 8;\n"
    "  return T;\n}\n")
_BME_HDR = ["#include <stdint.h>",
            "extern uint16_t dig_T1; extern int32_t dig_T2, dig_T3, t_fine;",
            "int32_t bme280_compensate_temperature(int32_t adc_T);"]
_BME_GOOD = [
    '#include "bme280_driver.h"',
    "int32_t bme280_compensate_temperature(int32_t adc_T){",
    "  int32_t var1,var2,T;",
    "  var1 = ((((adc_T>>3) - ((int32_t)dig_T1<<1))) * ((int32_t)dig_T2)) >> 11;",
    "  var2 = (((((adc_T>>4) - ((int32_t)dig_T1)) * ((adc_T>>4) - ((int32_t)dig_T1))) >> 12) * ((int32_t)dig_T3)) >> 14;",
    "  t_fine = var1 + var2;",
    "  T = (t_fine*5+128) >> 8;",
    "  return T;",
    "}",
]
_BME_ORACLE = {
    "kind": "reference_code", "entry": "bme280_compensate_temperature",
    "reference_entry": "BME280_compensate_T_int32", "reference_c": _BME_REF,
    "input_ctype": "int32_t", "output_ctype": "int32_t", "tolerance": "exact",
    "provenance": "detected", "source_pages": [25],
    "calibration": {"dig_T1": 27504, "dig_T2": 26435, "dig_T3": -1000, "t_fine": 0},
    "input_spread": [0, 131072, 262144, 519888, 400000, 16000, 524287, -50000],
}


# --- execution: table --------------------------------------------------------

@needs_cc
def test_table_faithful_conversion_passes():
    rep = ValidationReport()
    math_crosscheck({"lm75b_driver.h": _LM_HDR, "lm75b_driver.c": _LM_GOOD},
                    {"math_oracle": _LM_ORACLE}, rep)
    assert rep.checks["math_crosscheck"] == "pass"
    assert "lm75b_raw_to_celsius" in rep.verified_computation_entries


@needs_cc
def test_table_missing_sign_extend_is_caught():
    """The exact bug class: dropping two's-complement sign handling. The negative
    rows must expose it."""
    wrong = [ln for ln in _LM_GOOD if "s -= 0x200" not in ln]
    rep = ValidationReport()
    math_crosscheck({"lm75b_driver.h": _LM_HDR, "lm75b_driver.c": wrong},
                    {"math_oracle": _LM_ORACLE}, rep)
    assert rep.checks["math_crosscheck"] == "fail"
    assert any("511" in f.message for f in rep.failures)  # -0.5C row


@needs_cc
def test_table_missing_entry_point_fails():
    rep = ValidationReport()
    stub = ['#include "lm75b_driver.h"', "int unrelated(void){ return 0; }"]
    math_crosscheck({"lm75b_driver.h": _LM_HDR, "lm75b_driver.c": stub},
                    {"math_oracle": _LM_ORACLE}, rep)
    assert rep.checks["math_crosscheck"] == "fail"


# --- execution: reference-code differential ---------------------------------

@needs_cc
def test_reference_faithful_transcription_passes():
    rep = ValidationReport()
    math_crosscheck({"bme280_driver.h": _BME_HDR, "bme280_driver.c": _BME_GOOD},
                    {"math_oracle": _BME_ORACLE}, rep)
    assert rep.checks["math_crosscheck"] == "pass"


@needs_cc
def test_reference_transcription_error_is_caught():
    """>>2 where the datasheet has >>3 — compiles clean, wrong numbers."""
    wrong = [ln.replace("adc_T>>3", "adc_T>>2") for ln in _BME_GOOD]
    rep = ValidationReport()
    math_crosscheck({"bme280_driver.h": _BME_HDR, "bme280_driver.c": wrong},
                    {"math_oracle": _BME_ORACLE}, rep)
    assert rep.checks["math_crosscheck"] == "fail"


# --- applicability + guards --------------------------------------------------

def test_no_oracle_is_not_applicable_not_failure():
    rep = ValidationReport()
    math_crosscheck({"x.h": ["int x;"], "x.c": ["int x;"]}, {}, rep)
    assert rep.checks["math_crosscheck"] == "not_applicable"
    assert not rep.failures


def test_model_provenance_is_rejected():
    bad_oracle = dict(_LM_ORACLE, provenance="model")
    rep = ValidationReport()
    math_crosscheck({"lm75b_driver.h": _LM_HDR, "lm75b_driver.c": _LM_GOOD},
                    {"math_oracle": bad_oracle}, rep)
    assert rep.checks["math_crosscheck"] == "fail"
    assert any("never the model" in f.message for f in rep.failures)


# --- extraction from the real datasheets ------------------------------------

def test_lm75b_table_extracts_with_negatives():
    doc = _pdf("lm75b.pdf")
    o = extract_conversion_table(doc.pages, "LM75B")
    assert o is not None and o["kind"] == "table"
    assert o["provenance"] == "detected"
    assert sum(1 for v in o["vectors"] if v["out"] < 0) >= 1  # two's-complement rows
    # vectors are the register WORD (code left-justified into the read word), the
    # representation a real driver receives — 9-bit code 0x1FF (-0.5C) -> <<7.
    assert o["word_bits"] == 16
    assert {"in": 0x1FF << 7, "out": -0.5} in o["vectors"]
    assert {"in": 0x0FA << 7, "out": 125.0} in o["vectors"]


def test_bme280_reference_extracts():
    doc = _pdf("bme280.pdf")
    o = extract_reference_code(doc.pages, "BME280")
    assert o is not None and o["kind"] == "reference_code"
    assert "BME280_compensate_T_int32" in o["reference_c"]
    assert o["provenance"] == "detected"


def test_bmp180_has_no_oracle_stays_unverified():
    """The motivating chip: its worked example is a figure. No oracle must be
    extractable — the math stays UNVERIFIED, honestly."""
    doc = _pdf("bmp180.pdf")
    assert extract_math_oracle(doc.pages, "BMP180") is None


def test_bmp183_has_no_oracle_stays_unverified():
    doc = _pdf("1900_BMP183.pdf")
    assert extract_math_oracle(doc.pages, "BMP183") is None


# --- the promotion rule (both directions) -----------------------------------

def _report_with_marker(function: str) -> ValidationReport:
    rep = ValidationReport()
    rep.checks["compile"] = "pass"
    rep.checks["register_crosscheck"] = "pass"
    rep.unverified_computations.append(
        UnverifiedComputation(file="d.c", line=10, marker=COMPUTATION_MARKER,
                              function=function))
    return rep


def test_promotion_granted_when_math_covers_all():
    rep = _report_with_marker("lm75b_raw_to_celsius")
    rep.checks["math_crosscheck"] = "pass"
    rep.verified_computation_entries.append("lm75b_raw_to_celsius")
    rep.finalize()
    assert rep.status == "validated"


def test_promotion_denied_with_remaining_unverified_field():
    """The rule most likely to erode silently: a passing math check must NOT
    promote a driver that still has an unverified bit field."""
    rep = _report_with_marker("lm75b_raw_to_celsius")
    rep.checks["math_crosscheck"] = "pass"
    rep.verified_computation_entries.append("lm75b_raw_to_celsius")
    rep.unverified_fields.append(UnverifiedField(
        file="d.c", line=20, register="CFG", define="CFG_MODE_MASK",
        claimed_bits="[1:0]", has_unverified_comment=True))
    rep.finalize()
    assert rep.status == "validated-with-unverified-fields"


def test_promotion_denied_when_a_computation_is_uncovered():
    rep = _report_with_marker("compensate_temperature")   # covered below
    rep.unverified_computations.append(UnverifiedComputation(
        file="d.c", line=40, marker=COMPUTATION_MARKER,
        function="compensate_humidity"))                   # NOT covered
    rep.checks["math_crosscheck"] = "pass"
    rep.verified_computation_entries.append("compensate_temperature")
    rep.finalize()
    assert rep.status == "validated-with-unverified-fields"


def test_unverified_stays_when_math_check_skipped():
    """No compiler -> math check skipped -> markers are NOT cleared."""
    rep = _report_with_marker("lm75b_raw_to_celsius")
    rep.checks["math_crosscheck"] = "skipped"   # no verified entries recorded
    rep.finalize()
    assert rep.status == "validated-with-unverified-fields"


def test_scan_captures_enclosing_function():
    src = [
        "/* " + COMPUTATION_MARKER + " */",
        "float lm75b_raw_to_celsius(int32_t code) {",
        "  return code * 0.5f;",
        "}",
    ]
    rep = ValidationReport()
    scan_unverified_computations({"d.c": src}, rep)
    assert rep.unverified_computations[0].function == "lm75b_raw_to_celsius"
