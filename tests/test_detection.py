"""V1.6 Priority 2: front-matter detection accuracy.

Runs against the four known datasheets when present (accuracy report), plus a
synthetic multi-interface case and a no-detection case that do not need PDFs.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.detect import detect_metadata, shape_hint
from ingestion.loader import Document, Page

INPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "extraction", "input")

# (file, expected chip, expected vendor, expected interface set)
KNOWN = [
    ("bmp180.pdf", "BMP180", "Bosch", {"I2C"}),
    ("bme280.pdf", "BME280", "Bosch", {"I2C", "SPI"}),
    ("w25q64jv.pdf", "W25Q64JV", "Winbond", {"SPI"}),
    ("esp32_technical_reference_manual_en.pdf", "ESP32", "Espressif", {"I2C", "SPI", "UART"}),
]


@pytest.mark.parametrize("fname,chip,vendor,interfaces", KNOWN)
def test_detection_accuracy_on_known_datasheets(fname, chip, vendor, interfaces):
    path = os.path.join(INPUT_DIR, fname)
    if not os.path.exists(path):
        pytest.skip(f"{fname} not present")
    from ingestion.loader import load_document

    d = detect_metadata(load_document(path, max_pages=6))
    assert d["chip"]["value"] == chip
    assert d["chip"]["confidence"] == "high"
    assert d["chip"]["source_pages"]  # evidence recorded
    assert d["vendor"]["value"] == vendor
    got = {i["value"] for i in d.get("interfaces", [])}
    # every expected interface is surfaced (detection may find extra buses on the
    # big TRM; the required ones must all be present)
    assert interfaces <= got, f"{fname}: expected {interfaces}, got {got}"


def test_multi_interface_is_a_choice_not_a_pick():
    """A device that supports two buses must surface BOTH (as medium-confidence
    options), never silently pick one."""
    doc = Document(path="x.pdf", kind="pdf", pages=[
        Page(number=1, text="ACME42 sensor. Digital interface: I2C and SPI supported."),
    ])
    d = detect_metadata(doc)
    ifaces = {i["value"]: i["confidence"] for i in d["interfaces"]}
    assert set(ifaces) == {"I2C", "SPI"}
    assert all(c == "medium" for c in ifaces.values())  # forces a user choice


def test_no_detection_leaves_fields_absent():
    """No part number / no interface in the text -> keys simply absent (never a
    guessed value)."""
    doc = Document(path="x.pdf", kind="pdf", pages=[
        Page(number=1, text="This document describes a widget. No identifiers."),
    ])
    d = detect_metadata(doc)
    assert "chip" not in d
    assert "interfaces" not in d


def test_shape_hint_matches_router_intent():
    assert shape_hint(None, 0, 5)["value"] == "command_device"
    assert shape_hint("0x40000000", 30, 0)["value"] == "memory_mapped_peripheral"
    assert shape_hint(None, 30, 0)["value"] == "bus_attached_sensor"
