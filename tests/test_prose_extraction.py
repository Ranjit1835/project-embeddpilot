"""V1.7: prose bit-field extraction for MCU reference manuals.

The spike found bit-diagram summary tables reverse cell order in the PDF text
layer, so bit-field names from tables are garbage; the per-bit 'Bit N NAME:'
prose is clean. These tests pin the prose parser's behaviour with synthetic
RM-style text (no PDF dependency)."""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from ingestion.loader import Document, Page
from ingestion.prose import (
    parse_bit_fields_prose,
    parse_bit_line,
    scan_prose_registers,
)


# --- single-line parsing --------------------------------------------------------

def test_single_bit_line():
    f = parse_bit_line("Bit 21 I2C1EN: I2C1 clock enable")
    assert f is not None
    assert (f.name, f.bits) == ("I2C1EN", "[21:21]")
    assert f.description == "I2C1 clock enable"


def test_bit_range_line():
    f = parse_bit_line("Bits 15:8 FREQ: Peripheral clock frequency")
    assert (f.name, f.bits) == ("FREQ", "[15:8]")


def test_embedded_range_in_name_is_stripped_bits_win():
    # positions come from the 'Bits 15:8' prefix, not the label's [5:0]
    f = parse_bit_line("Bits 15:8 FREQ[5:0]: Peripheral clock frequency")
    assert (f.name, f.bits) == ("FREQ", "[15:8]")


def test_reserved_lines_are_not_fields():
    assert parse_bit_line("Bits 31:24 Reserved, must be kept at reset value.") is None
    assert parse_bit_line("Bit 15 Reserved") is None


def test_non_bit_lines_ignored():
    assert parse_bit_line("0: I2C1 clock disabled") is None
    assert parse_bit_line("Address offset: 0x40") is None
    assert parse_bit_line("The CCR bits generate the SCL clock.") is None


def test_reversed_high_low_is_normalized():
    f = parse_bit_line("Bits 8:15 FOO: swapped order")
    assert f.bits == "[15:8]"


# --- block parsing --------------------------------------------------------------

def test_block_parse_and_dedupe():
    lines = [
        "Bit 10 AF: Acknowledge failure",
        "1: Acknowledge failure detected",          # value enum, ignored
        "Bit 9 ARLO: Arbitration lost",
        "Bit 10 AF: (restated later)",              # duplicate position -> dropped
    ]
    fields = parse_bit_fields_prose(lines)
    assert [f.name for f in fields] == ["AF", "ARLO"]


# --- section scanning -----------------------------------------------------------

RCC_APB1ENR_TEXT = """6.3.13 RCC APB1 peripheral clock enable register (RCC_APB1ENR)
Address offset: 0x40
Reset value: 0x0000 0000
Bit 23 I2C3EN: I2C3 clock enable
Bit 22 I2C2EN: I2C2 clock enable
Bit 21 I2C1EN: I2C1 clock enable
0: I2C1 clock disabled
1: I2C1 clock enabled
Bits 20:18 Reserved, must be kept at reset value."""

I2C_SR1_TEXT = """27.6.6 I2C Status register 1 (I2C_SR1)
Address offset: 0x14
Reset value: 0x0000
Bit 11 OVR: Overrun/Underrun
Bit 10 AF: Acknowledge failure
Bit 9 ARLO: Arbitration lost (master mode)
Bit 8 BERR: Bus error"""


def _doc(*page_texts: str) -> Document:
    return Document(path="rm.pdf", kind="pdf",
                    pages=[Page(number=i + 1, text=t) for i, t in enumerate(page_texts)])


def test_scan_recovers_register_offset_reset_and_fields():
    regs = scan_prose_registers(_doc(RCC_APB1ENR_TEXT))
    assert len(regs) == 1
    r = regs[0]
    assert r.name == "RCC_APB1ENR"
    assert r.offset == "0x40"
    assert r.reset_value == "0x00000000"
    assert r.confidence == "high"
    # the clock cross-check datum, exact:
    i2c1 = [f for f in r.fields if f.name == "I2C1EN"]
    assert i2c1 and i2c1[0].bits == "[21:21]"
    assert "Reserved" not in [f.name for f in r.fields]


def test_scan_error_flags_have_exact_positions():
    r = scan_prose_registers(_doc(I2C_SR1_TEXT))[0]
    got = {f.name: f.bits for f in r.fields}
    assert got["BERR"] == "[8:8]"
    assert got["ARLO"] == "[9:9]"
    assert got["AF"] == "[10:10]"
    assert got["OVR"] == "[11:11]"


def test_two_registers_separated_by_headings():
    regs = scan_prose_registers(_doc(RCC_APB1ENR_TEXT + "\n" + I2C_SR1_TEXT))
    assert [r.name for r in regs] == ["RCC_APB1ENR", "I2C_SR1"]
    assert regs[1].offset == "0x14"


def test_section_spanning_page_boundary_keeps_provenance():
    # heading + offset on p1, bit lines on p2 -> both pages in source_pages
    head = ("27.6.6 I2C Status register 1 (I2C_SR1)\n"
            "Address offset: 0x14\nReset value: 0x0000")
    body = "Bit 8 BERR: Bus error\nBit 10 AF: Acknowledge failure"
    r = scan_prose_registers(_doc(head, body))[0]
    assert r.source_pages == [1, 2]
    assert {f.name for f in r.fields} == {"BERR", "AF"}


def test_page_range_targeting_skips_unwanted_pages():
    regs = scan_prose_registers(_doc(RCC_APB1ENR_TEXT, I2C_SR1_TEXT), pages=[2])
    assert [r.name for r in regs] == ["I2C_SR1"]


def test_false_heading_without_offset_or_fields_dropped():
    # a stray 'register (FOO)' mention with no offset and no bit lines is noise
    regs = scan_prose_registers(_doc("see the control register (FOO) for details"))
    assert regs == []
