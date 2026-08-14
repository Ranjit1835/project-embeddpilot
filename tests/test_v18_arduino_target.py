"""V1.8 Part A + D: Arduino output target and the scope-honesty panel.

Fast, deterministic tests (mocked LLM, no arduino-cli). The live multi-core
compile is exercised separately by the smoke test and the recorded live runs in
V1.8_REPORT.md; here we lock the generation SHAPE, bus selection, keyword/
library.properties generation, the scope panel, and the three-state finalize.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generation.provider import MockProvider
from generation.router import route
from generation.worker import _arduino_bus, generate_driver
from validator.report import UnverifiedComputation, ValidationReport
from validator.scope import build_scope

SPI_MAP = {
    "chip": "BMP183", "peripheral": "SPI",
    "provenance": {"chip": "user", "peripheral": "user"},
    "base_address": None,
    "registers": [{"name": "WHOAMI", "offset": "0xD0", "fields": [],
                   "source_pages": [1], "confidence": "high"}],
    "commands": [], "detected": {}, "warnings": [],
}

CANNED_LIB = {
    "header_cpp": (
        "#pragma once\n#include <Arduino.h>\n#include <SPI.h>\n"
        "#define BMP183_WHOAMI_ADDR 0xD0\n"
        "class BMP183 {\npublic:\n"
        "  BMP183(SPIClass &bus = SPI, uint8_t cs = 10);\n"
        "  bool begin();\n  bool readTemperature(float &t);\n};\n"
    ),
    "source_cpp": (
        '#include "BMP183.h"\n'
        "BMP183::BMP183(SPIClass &, uint8_t) {}\n"
        "bool BMP183::begin() { return true; }\n"
        "bool BMP183::readTemperature(float &t) { t = 0; return true; }\n"
    ),
    "example_ino": "#include <BMP183.h>\nBMP183 s;\nvoid setup() {}\nvoid loop() {}\n",
    "readme_md": "# BMP183\n",
    "notes": "",
}

EXPECTED_FILES = {
    "BMP183/library.properties",
    "BMP183/keywords.txt",
    "BMP183/src/BMP183.h",
    "BMP183/src/BMP183.cpp",
    "BMP183/examples/BasicRead/BasicRead.ino",
    "BMP183/README.md",
}


def test_arduino_generation_produces_standard_library_layout():
    dec = route(SPI_MAP, "arduino", log=False)
    res = generate_driver(MockProvider([CANNED_LIB]), SPI_MAP, dec, "arduino",
                          target="arduino")
    assert set(res.files) == EXPECTED_FILES
    assert "name=BMP183" in res.files["BMP183/library.properties"]
    assert "architectures=*" in res.files["BMP183/library.properties"]
    # keywords.txt: class as KEYWORD1, public methods as KEYWORD2
    kw = res.files["BMP183/keywords.txt"]
    assert "BMP183\tKEYWORD1" in kw
    assert "readTemperature\tKEYWORD2" in kw
    assert "begin\tKEYWORD2" in kw
    # the class is named after the chip (B1 consistency by construction)
    assert "class BMP183" in res.files["BMP183/src/BMP183.h"]


def test_arduino_bus_selection():
    assert _arduino_bus({"peripheral": "I2C"}) == "I2C"
    assert _arduino_bus({"peripheral": "I2C1"}) == "I2C"
    assert _arduino_bus({"peripheral": "SPI"}) == "SPI"
    # a non-bus label falls back by shape: commands -> SPI, else I2C
    assert _arduino_bus({"peripheral": "pressure", "commands": [{"opcode": "0x2E"}]}) == "SPI"
    assert _arduino_bus({"peripheral": "pressure"}) == "I2C"


# --- Part D scope-honesty panel ---------------------------------------------

def _passing_report():
    r = ValidationReport()
    r.checks = {"register_crosscheck": "pass", "compile": "pass"}
    return r


def test_scope_arduino_marks_clock_gpio_init_platform_owned():
    scope = {s["item"]: s for s in build_scope("arduino", SPI_MAP, _passing_report(), False)}
    assert scope[2]["status"] == "cross-checked"      # register map
    assert scope[4]["status"] == "platform-owned"     # clock
    assert scope[5]["status"] == "platform-owned"     # gpio/pins
    assert scope[6]["status"] == "platform-owned"     # init sequence
    assert scope[7]["status"] == "cross-checked"      # error conditions


def test_scope_bare_metal_without_mcu_map_marks_clock_not_covered():
    scope = {s["item"]: s for s in build_scope("bare-metal", SPI_MAP, _passing_report(), False)}
    assert scope[4]["status"] == "not-covered"
    assert scope[5]["status"] == "not-covered"


def test_scope_bare_metal_with_mcu_map_cross_checks_clock():
    scope = {s["item"]: s for s in build_scope("bare-metal", SPI_MAP, _passing_report(), True)}
    assert scope[4]["status"] == "cross-checked"
    assert scope[6]["status"] == "marked-unverified"  # init sequence


# --- three-state verdict with Arduino cores ---------------------------------

def test_finalize_all_cores_pass_is_validated():
    r = _passing_report()
    r.cores = [{"name": "ESP32-S3", "result": "pass"}]
    r.finalize()
    assert r.status == "validated"


def test_finalize_compensation_math_downgrades():
    r = _passing_report()
    r.unverified_computations = [UnverifiedComputation("BMP183.cpp", 42, "m")]
    r.finalize()
    assert r.status == "validated-with-unverified-fields"


def test_finalize_skipped_compile_is_not_validated():
    r = ValidationReport()
    r.checks = {"register_crosscheck": "pass", "compile": "skipped"}
    r.finalize()
    assert r.status == "failed"  # a judge that did not run passes no one
