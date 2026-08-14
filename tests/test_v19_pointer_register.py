"""V1.9 item 2: pointer-register extraction (TMP100, LM75B, MCP9808).

Unit tests on the exact table shapes + datasheet-backed extraction (skips where
the git-ignored PDFs are absent).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.tables import LogicalTable
from ingestion.registers import (
    classify_table,
    parse_pointer_register_table,
    parse_register_index,
)

# TMP100 p.15 Table 5 — [P1, P0, TYPE, REGISTER]
TMP100_PTR = LogicalTable(
    header=["P1", "P0", "TYPE", "REGISTER"],
    rows=[
        ["0", "0", "Ronly,default", "TemperatureRegister"],
        ["0", "1", "R/W", "ConfigurationRegister"],
        ["1", "0", "R/W", "T Register LOW"],
        ["1", "1", "R/W", "T Register HIGH"],
    ],
    source_pages=[15],
)

# LM75B p.16 — header lives in the first body row [P2, P1, P0, Register]
LM75B_PTR = LogicalTable(
    header=["", "", "", ""],
    rows=[
        ["P2", "P1", "P0", "Register"],
        ["0", "0", "0", "Temperature(Readonly)(Power-updefault)"],
        ["0", "0", "1", "Configuration(Read/Write)"],
        ["0", "1", "0", "T (Read/Write) HYST"],
        ["0", "1", "1", "T (Read/Write) OS"],
    ],
    source_pages=[16],
)

# MCP9808 p.33 — two-row header, direct hex addresses
MCP9808_REG = LogicalTable(
    header=["Registers", "", "Default Register Data (Hexadecimal)",
            "Power-Up Default Register Description"],
    rows=[
        ["Address (Hexadecimal)", "Register Name", "", ""],
        ["0x01", "CONFIG", "0x0000", "Comparator Mode ..."],
        ["0x02", "T UPPER", "0x0000", "0C"],
        ["0x05", "T A", "0x0000", "0C"],
        ["0x06", "Manufacturer ID", "0x0054", "0x0054"],
        ["0x08", "Resolution", "0x03", "0x03"],
    ],
    source_pages=[33],
)


def test_tmp100_pointer_table():
    assert classify_table(TMP100_PTR) == "pointer_register"
    regs = {r.name: (r.offset, r.access) for r in parse_pointer_register_table(TMP100_PTR)}
    assert regs["Temperature"] == ("0x00", "RO")
    assert regs["Configuration"] == ("0x01", "RW")
    assert regs["T_LOW"] == ("0x02", "RW")
    assert regs["T_HIGH"] == ("0x03", "RW")


def test_lm75b_pointer_table_with_subheader_in_first_row():
    assert classify_table(LM75B_PTR) == "pointer_register"
    regs = {r.name: r.offset for r in parse_pointer_register_table(LM75B_PTR)}
    assert regs == {"Temperature": "0x00", "Configuration": "0x01",
                    "T_HYST": "0x02", "T_OS": "0x03"}


def test_mcp9808_two_row_header_direct_addresses():
    assert classify_table(MCP9808_REG) == "register_index"
    regs = {r.name: r.offset for r in parse_register_index(MCP9808_REG)}
    assert regs.get("CONFIG") == "0x01"
    assert regs.get("Resolution") == "0x08"
    assert "Manufacturer ID" in regs


# --- datasheet-backed ---

INPUT = os.path.join(os.path.dirname(__file__), "..", "extraction", "input")
CASES = [
    ("tmp101.pdf", 4, "pointer"),
    ("lm75b.pdf", 4, "pointer"),
    ("MCP9808-0.5C-Maximum-Accuracy-Digital-Temperature-Sensor-Data-Sheet-DS20005095B.pdf", 8, "direct"),
]


@pytest.mark.parametrize("fname,min_regs,pattern", CASES)
def test_pointer_register_extraction_end_to_end(fname, min_regs, pattern):
    path = os.path.join(INPUT, fname)
    if not os.path.exists(path):
        pytest.skip(f"{fname} not present")
    from ingestion.pipeline import ingest_datasheet
    m = ingest_datasheet(path)
    assert len(m["registers"]) >= min_regs, m["registers"]
    assert m.get("access_pattern") == pattern
    # every register offset is a small pointer/register address
    for r in m["registers"]:
        assert int(r["offset"], 16) < 0x100
