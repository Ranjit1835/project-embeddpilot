"""V1.8 datasheet-backed regression tests (B1, B2, B3).

These run against the engineers' real datasheets in extraction/input/. Those
PDFs are git-ignored, so the tests SKIP where the files are absent (same policy
as test_detection.py) and RUN wherever the datasheets are present.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.detect import detect_metadata
from ingestion.loader import load_document
from generation.inputs import (
    UnsupportedInterfaceError,
    assert_supported_interface,
    canonical_bus,
)

INPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "extraction", "input")


def _detect(fname: str) -> dict:
    path = os.path.join(INPUT_DIR, fname)
    if not os.path.exists(path):
        pytest.skip(f"{fname} not present")
    return detect_metadata(load_document(path, max_pages=6))


# --- B1: BMP183 must identify as BMP183/SPI, never an I2C sibling ------------

def test_b1_bmp183_identified_as_bmp183_not_a_sibling():
    d = _detect("1900_BMP183.pdf")
    assert d["chip"]["value"] == "BMP183"
    assert d["chip"]["confidence"] == "high"
    assert d["chip"]["value"] not in ("BMP180", "BMP085")  # the wrong-sibling bug
    ifaces = {i["value"] for i in d.get("interfaces", [])}
    assert "SPI" in ifaces  # BMP183 is SPI — flipping this builds the wrong driver


# --- B2: TMP107 is SMAART Wire / UART — detected and blocked -----------------

def test_b2_tmp107_uart_is_blocked_not_generated():
    d = _detect("tmp107.pdf")
    assert d["chip"]["value"] == "TMP107"
    ifaces = {i["value"] for i in d.get("interfaces", [])}
    assert "UART" in ifaces
    # the detected bus is outside {I2C, SPI} -> generation must be blocked
    detected_bus = next(iter(ifaces))
    assert canonical_bus(detected_bus) not in ("I2C", "SPI")
    with pytest.raises(UnsupportedInterfaceError):
        assert_supported_interface(detected_bus)


# --- B3: held-out detection accuracy on the four engineer chips --------------

HELD_OUT = [
    ("1900_BMP183.pdf", "BMP183", "SPI"),
    ("tmp107.pdf", "TMP107", "UART"),
    ("tmp125.pdf", "TMP125", "SPI"),
    ("tmp101.pdf", "TMP100", "I2C"),   # combined TMP100/TMP101 datasheet
]


@pytest.mark.parametrize("fname,chip,iface", HELD_OUT)
def test_b3_held_out_detection_accuracy(fname, chip, iface):
    d = _detect(fname)
    assert d["chip"]["value"] == chip, f"{fname}: got {d.get('chip')}"
    assert d["chip"]["confidence"] == "high"
    assert iface in {i["value"] for i in d.get("interfaces", [])}
