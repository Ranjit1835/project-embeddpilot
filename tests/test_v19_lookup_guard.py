"""V1.9 item 1: a value->digital-output lookup table must never classify as a
register index. A spurious register would poison the map the cross-check
validator treats as ground truth, so the judge would confidently validate a
wrong driver against a wrong map. Uses the actual TMP100 and LM75B lookup tables.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.tables import LogicalTable
from ingestion.registers import (
    classify_table,
    parse_headerless,
    parse_register_index,
)

# TMP100 p.9-10: Temperature / DIGITAL OUTPUT (binary, hex). Headerless.
TMP100_LOOKUP = LogicalTable(
    header=["", "", ""],
    rows=[
        ["TEMPERATURE (°C)", "DIGITAL", "OUTPUT"],
        ["", "BINARY", "HEX"],
        ["128", "011111111111", "7FF"],
        ["127.9375", "011111111111", "7FF"],
        ["100", "011001000000", "640"],
        ["80", "010100000000", "500"],
        ["75", "010010110000", "4B0"],
        ["50", "001100100000", "320"],
        ["25", "000110010000", "190"],
        ["0.25", "000000000100", "004"],
        ["0", "000000000000", "000"],
    ],
    source_pages=[9, 10],
)

# LM75B p.14: Temperature / Digital Output (Binary, Hex). Headerless.
LM75B_LOOKUP = LogicalTable(
    header=["", "", ""],
    rows=[
        ["Temperature", "DigitalOutput", ""],
        ["", "Binary", "Hex"],
        ["125°C", "011111010", "0FAh"],
        ["25°C", "000110010", "032h"],
        ["0.5°C", "000000001", "001h"],
        ["0°C", "000000000", "000h"],
        ["-25°C", "111001110", "1CEh"],
        ["-55°C", "110010010", "192h"],
    ],
    source_pages=[14],
)


def test_tmp100_lookup_is_not_a_register_table():
    assert classify_table(TMP100_LOOKUP) == "other"
    assert parse_headerless(TMP100_LOOKUP) == []
    assert parse_register_index(TMP100_LOOKUP) == []


def test_lm75b_lookup_is_not_a_register_table():
    assert classify_table(LM75B_LOOKUP) == "other"
    assert parse_headerless(LM75B_LOOKUP) == []


def test_no_spurious_registers_from_a_binary_code_lookup():
    """A lookup whose value column IS identifier-shaped must still emit nothing —
    the binary code column is the tell, not the value column's shape."""
    t = LogicalTable(
        header=["", "", ""],
        rows=[
            ["STATE", "CODE", ""],
            ["IDLE", "000000", "00h"],
            ["ARMED", "000001", "01h"],
            ["FIRING", "000010", "02h"],
            ["COOLDOWN", "000011", "03h"],
        ],
        source_pages=[7],
    )
    assert classify_table(t) == "other"
    assert parse_headerless(t) == []
    assert parse_register_index(t) == []


def test_real_register_index_still_classifies_and_parses():
    """Recall guard: a genuine register-index table (with an access column) is
    unaffected by the lookup guard."""
    t = LogicalTable(
        header=["Register", "Address", "Access", "Reset"],
        rows=[
            ["CONFIG", "0x01", "R/W", "0x00"],
            ["T_UPPER", "0x02", "R/W", "0x00"],
            ["T_LOWER", "0x03", "R/W", "0x00"],
            ["MANUF_ID", "0x06", "RO", "0x54"],
        ],
        source_pages=[33],
    )
    assert classify_table(t) == "register_index"
    regs = parse_register_index(t)
    assert {r.name for r in regs} == {"CONFIG", "T_UPPER", "T_LOWER", "MANUF_ID"}
    assert {r.offset for r in regs} == {"0x01", "0x02", "0x03", "0x06"}
