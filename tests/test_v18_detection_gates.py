"""V1.8 detection & interface gates (B1 + B2).

These are unit tests that do not need the engineer datasheets: they exercise the
exact-token-wins rule, the supported-interface block, the interface-vs-document
cross-check, and the chip-consistency assertion with synthetic inputs. The
datasheet-backed reproduction/regression tests live alongside the real PDFs.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.detect import detect_metadata
from ingestion.loader import Document, Page
from generation.inputs import (
    ChipConsistencyError,
    InterfaceMismatchError,
    UnsupportedInterfaceError,
    assert_chip_consistency,
    assert_input_provenance,
    assert_interface_matches_document,
    assert_supported_interface,
    canonical_bus,
)


# --- B1: exact printed part number wins over a family sibling -----------------

def test_exact_title_part_beats_family_sibling_mention():
    """A BMP183 datasheet that also mentions its I2C siblings BMP180/BMP085 in
    the body must still be identified as BMP183 (the title subject), not the
    family-pattern sibling. Getting this wrong flips SPI->I2C."""
    doc = Document(path="bmp183.pdf", kind="pdf", pages=[
        Page(number=1, text="BMP183 Digital pressure sensor. SPI interface. Bosch Sensortec."),
        Page(number=2, text="The BMP183 is the SPI companion to the I2C BMP180 and replaces the BMP085."),
        Page(number=3, text="Register map. Pin compatible considerations vs BMP180."),
    ])
    d = detect_metadata(doc)
    assert d["chip"]["value"] == "BMP183"
    assert d["chip"]["confidence"] == "high"
    assert 1 in d["chip"]["source_pages"]  # identified from the title page


def test_family_still_identifies_when_no_exact_title_token():
    """No standalone part token in the title (spaced 'BME 280') -> the curated
    family still identifies it confidently (no regression on known parts)."""
    doc = Document(path="bme280.pdf", kind="pdf", pages=[
        Page(number=1, text="BME 280 Combined humidity and pressure sensor. Bosch."),
    ])
    d = detect_metadata(doc)
    assert d["chip"]["value"] == "BME280"
    assert d["chip"]["confidence"] == "high"


# --- B2: supported-interface gate --------------------------------------------

@pytest.mark.parametrize("periph,expected", [
    ("I2C", "I2C"), ("I2C1", "I2C"), ("IIC", "I2C"), ("TWI", "I2C"),
    ("SPI", "SPI"), ("SPI2", "SPI"),
    ("UART", "UART"), ("USART3", "UART"),
    ("SMAART Wire", "SMAART Wire"),
    ("1-Wire", "1-Wire"),
    ("pressure-sensor", None),  # a device role, not a bus -> ignored by the gate
    ("", None),
])
def test_canonical_bus(periph, expected):
    assert canonical_bus(periph) == expected


def test_non_bus_peripheral_descriptor_is_not_blocked():
    """A legacy 'peripheral' used as a device role must not trip the bus gate."""
    assert_supported_interface("pressure-sensor")  # no raise


@pytest.mark.parametrize("periph", ["I2C", "I2C1", "SPI", "SPI2"])
def test_supported_interfaces_pass(periph):
    assert_supported_interface(periph)  # no raise


@pytest.mark.parametrize("periph", ["UART", "USART1", "SMAART Wire", "1-Wire"])
def test_unsupported_interface_blocks(periph):
    with pytest.raises(UnsupportedInterfaceError) as e:
        assert_supported_interface(periph)
    assert "I2C and SPI" in str(e.value)


def test_tmp107_smaart_wire_blocked_through_provenance_gate():
    """TMP107 (SMAART Wire) must be blocked at the same gate that guards
    provenance — a clean provenance does not make an unsupported bus generable."""
    m = {
        "chip": "TMP107", "peripheral": "SMAART Wire",
        "provenance": {"chip": "user", "peripheral": "user"},
    }
    with pytest.raises(UnsupportedInterfaceError):
        assert_input_provenance(m, "esp32")


# --- B1: interface must not contradict the document --------------------------

def test_interface_mismatch_blocks_when_doc_is_single_bus():
    m = {
        "chip": "BMP183", "peripheral": "I2C",
        "provenance": {"chip": "user", "peripheral": "user"},
        "detected": {"interfaces": [{"value": "SPI", "confidence": "high", "source_pages": [1]}]},
    }
    with pytest.raises(InterfaceMismatchError):
        assert_interface_matches_document(m)


def test_interface_multi_bus_document_is_not_blocked():
    m = {
        "chip": "BME280", "peripheral": "I2C",
        "detected": {"interfaces": [
            {"value": "I2C", "confidence": "medium", "source_pages": [1]},
            {"value": "SPI", "confidence": "medium", "source_pages": [1]},
        ]},
    }
    assert_interface_matches_document(m)  # no raise — a legitimate user choice


# --- B1: chip-consistency hard gate ------------------------------------------

def test_chip_consistency_passes_when_all_agree():
    assert_chip_consistency("BMP183", "BMP183", ["bmp183_driver.c", "bmp183_driver.h"])


def test_chip_consistency_fails_on_detected_vs_map_disagreement():
    with pytest.raises(ChipConsistencyError):
        assert_chip_consistency("BMP183", "BMP085", ["bmp183_driver.c"])


def test_chip_consistency_fails_on_generated_name_disagreement():
    with pytest.raises(ChipConsistencyError):
        assert_chip_consistency("BMP183", None, ["bmp085_driver.c", "bmp085_driver.h"])
