"""Regression tests for the V1.5 ingestion spike.

Synthetic tables reproduce the exact pathologies observed in real datasheets
(BMP180, BME280, ESP32 TRM, W25Q64JV) so parser fixes stay fixed without
needing the PDFs present.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.loader import Document, Page
from ingestion.pipeline import SCHEMA_PATH, _dedupe, _merge_relative_absolute
from ingestion.registers import (
    ExtractedRegister,
    _norm_hex,
    _norm_hex_pair,
    _parse_field_label,
    classify_table,
    parse_bit_column_map,
    parse_headerless,
    parse_register_index,
)
from ingestion.tables import LogicalTable, stitch_tables


# --- hex strictness: garbled cells must not become numbers -------------------

@pytest.mark.parametrize("cell,expected", [
    ("0xAA", "0xAA"),
    ("F8h", "0xF8"),
    ("00h", "0x00"),
    ("n/a", None),
    ("stat0e0 h", None),          # garbled reset cell, BMP180 p18
    ("BFh d own to AAh", None),   # garbled range row, BMP180 p18
    ("20", None),                 # electrical value, NOT address 0x14 (BME280)
    ("0x88 / 0x89", None),        # pairs are not single values
])
def test_norm_hex_strict(cell, expected):
    assert _norm_hex(cell) == expected


def test_hex_pair():
    assert _norm_hex_pair("0x88 / 0x89") == ["0x88", "0x89"]
    assert _norm_hex_pair("0x88") is None


# --- field labels: embedded ranges give name + width -------------------------

@pytest.mark.parametrize("label,name,width", [
    ("adc_out_xlsb<7:3", "adc_out_xlsb", 5),
    ("> adc_out_lsb<7:0", "adc_out_lsb", 8),
    ("osrs_t[2:0]", "osrs_t", 3),
    ("spi3w_en[0]", "spi3w_en", 1),
    ("id<7:0> control", "id", 8),
    ("0", None, None),            # hardwired bit, not a field
    ("x", None, None),
])
def test_parse_field_label(label, name, width):
    assert _parse_field_label(label) == (name, width)


# --- bit-column maps: merged spans, width clipping, reset column -------------

BME280_STATUS_STYLE = LogicalTable(
    header=["Register Name", "Address", "bit7", "bit6", "bit5", "bit4",
            "bit3", "bit2", "bit1", "bit0", "Reset state"],
    rows=[
        ["ctrl_meas", "0xF4", "osrs_t[2:0]", "", "", "osrs_p[2:0]", "", "",
         "mode[1:0]", "", "0x00"],
        # measuring[0] followed by empties is a 1-bit field + reserved gap
        ["status", "0xF3", "", "", "", "", "measuring[0]", "", "",
         "im_update[0]", "0x00"],
    ],
    source_pages=[27],
)


def test_bit_column_spans_and_width_clip():
    regs = {r.name: r for r in parse_bit_column_map(BME280_STATUS_STYLE)}
    ctrl = regs["ctrl_meas"]
    assert [(f.name, f.bits) for f in ctrl.fields] == [
        ("osrs_t", "[7:5]"), ("osrs_p", "[4:2]"), ("mode", "[1:0]"),
    ]
    assert ctrl.reset_value == "0x00"
    status = regs["status"]
    assert [(f.name, f.bits) for f in status.fields] == [
        ("measuring", "[3:3]"), ("im_update", "[0:0]"),
    ]


# --- register-index tables: subheaders must not become registers -------------

ESP32_SUMMARY_STYLE = LogicalTable(
    header=["Name", "Description", "I2C0", "I2C1", "Acc"],
    rows=[
        ["Configuration registers", "", "", "", ""],       # subheader
        ["I2C_CTR_REG", "Transmission config", "0x0004", "0x0004", "R/W"],
        ["I2C_TO_REG", "Timeout control", "0x000C", "0x000C", "R/W"],
        ["I2C_FIFO_CONF_REG", "FIFO config", "0x0018", "0x0018", "R/W"],
        ["Status registers", "", "", "", ""],              # subheader
        ["I2C_SR_REG", "Work status", "0x0008", "0x0008", "RO"],
    ],
    source_pages=[401],
)


def test_register_index_skips_subheaders_and_finds_hex_column():
    assert classify_table(ESP32_SUMMARY_STYLE) == "register_index"
    regs = parse_register_index(ESP32_SUMMARY_STYLE)
    assert [(r.name, r.offset, r.access) for r in regs] == [
        ("I2C_CTR_REG", "0x0004", "RW"),
        ("I2C_TO_REG", "0x000C", "RW"),
        ("I2C_FIFO_CONF_REG", "0x0018", "RW"),
        ("I2C_SR_REG", "0x0008", "RO"),
    ]


# --- MSB/LSB pairs (BMP180 calibration layout) --------------------------------

BMP180_CALIB_STYLE = LogicalTable(
    header=["", "", "", ""],
    rows=[
        ["", "Parameter", "MSB", "LSB"],
        ["", "AC1", "0xAA", "0xAB"],
        ["", "AC2", "0xAC", "0xAD"],
        ["", "AC3", "0xAE", "0xAF"],
    ],
    source_pages=[13],
)


def test_msb_lsb_pair_emits_two_registers_per_row():
    kind = classify_table(BMP180_CALIB_STYLE)
    regs = (
        parse_register_index(BMP180_CALIB_STYLE)
        if kind.startswith("register_index") and kind != "register_index_headerless"
        else parse_headerless(BMP180_CALIB_STYLE)
    )
    got = {(r.name, r.offset) for r in regs}
    assert {("AC1_MSB", "0xAA"), ("AC1_LSB", "0xAB"),
            ("AC3_MSB", "0xAE"), ("AC3_LSB", "0xAF")} <= got


# --- paired cells (BME280 compensation table) ---------------------------------

BME280_CALIB_STYLE = LogicalTable(
    header=["Register Address", "Register content", "Data type"],
    rows=[
        ["0x88 / 0x89", "dig_T1 [7:0] / [15:8]", "unsigned short"],
        ["0x8A / 0x8B", "dig_T2 [7:0] / [15:8]", "signed short"],
        ["0xA1", "dig_H1 [7:0]", "unsigned char"],
    ],
    source_pages=[24],
)


def test_paired_address_cells_split():
    regs = parse_register_index(BME280_CALIB_STYLE)
    got = {(r.name, r.offset) for r in regs}
    assert {("dig_T1_LSB", "0x88"), ("dig_T1_MSB", "0x89"),
            ("dig_T2_LSB", "0x8A"), ("dig_T2_MSB", "0x8B"),
            ("dig_H1", "0xA1")} <= got


# --- headerless salvage must reject command/timing tables ---------------------

BMP180_COMMAND_TABLE = LogicalTable(
    header=["", "", "", ""],
    rows=[
        ["", "Measurement", "(register address 0xF4)", "[ms]"],
        ["", "Temperature", "0x2E", "4.5"],
        ["Pressure (oss = 0)", "", "0x34", "4.5"],
        ["", "", "0x74", "7.5"],
    ],
    source_pages=[21],
)


def test_headerless_rejects_sparse_command_tables():
    assert parse_headerless(BMP180_COMMAND_TABLE) == []


# --- multi-page stitching with repeated headers -------------------------------

def test_stitch_repeated_headers():
    doc = Document(path="x.pdf", kind="pdf", pages=[
        Page(number=1, text="", tables=[[
            ["Name", "Address", "Access"],
            ["REG_A", "0x00", "R/W"],
        ]]),
        Page(number=2, text="", tables=[[
            ["Name", "Address", "Access"],   # repeated header: continuation
            ["REG_B", "0x04", "RO"],
        ]]),
    ])
    tables = stitch_tables(doc)
    assert len(tables) == 1
    assert tables[0].source_pages == [1, 2]
    assert len(tables[0].rows) == 2


# --- relative/absolute merge + base inference ----------------------------------

def test_merge_relative_absolute_and_rebase():
    regs = [
        ExtractedRegister(name="I2C_CTR_REG", offset="0x0004"),
        ExtractedRegister(name="I2C_CTR_REG", offset="0x3FF53004", access="RW"),
        # seen ONLY absolute; must be rebased with the inferred base
        ExtractedRegister(name="I2C_COMD0_REG", offset="0x3FF53058"),
    ]
    warnings: list[str] = []
    out, base_address = _merge_relative_absolute(_dedupe(regs), warnings)
    merged = {r.name: r for r in out}
    assert merged["I2C_CTR_REG"].offset == "0x0004"
    assert merged["I2C_CTR_REG"].access == "RW"  # merged from the absolute copy
    assert merged["I2C_COMD0_REG"].offset == "0x0058"
    assert base_address == "0x3FF53000"  # inferred base carried into the map
    assert any("rebased" in w for w in warnings)


# --- placeholder registers merge into named ones -------------------------------

def test_placeholder_merges_into_named():
    regs = [
        ExtractedRegister(name="press_msb", offset="0xF7", reset_value="0x80"),
        ExtractedRegister(name="REG_0xF7", offset="0xF7", access="RO"),
    ]
    out = _dedupe(regs)
    assert len(out) == 1
    assert out[0].name == "press_msb"
    assert out[0].access == "RO"


# --- command tables (Amendment 2) ----------------------------------------------

from ingestion.commands import is_command_table, parse_command_table

W25Q64_INSTRUCTION_STYLE = LogicalTable(
    header=[""] * 6,  # real header lands in row 0 (not register-header shaped)
    rows=[
        ["Data Input Output", "Byte 1", "Byte 2", "Byte 3", "Byte 4", "Byte 5"],
        ["Number of Clock(1-1-1)", "8", "8", "8", "8", "8"],
        ["Write Enable", "06h", "", "", "", ""],
        ["Read Data", "03h", "A23-A16", "A15-A8", "A7-A0", "(D7-D0)"],
        ["Page Program", "02h", "A23-A16", "A15-A8", "A7-A0", "D7-D0"],
        ["Release Power-down / ID", "ABh", "Dummy", "Dummy", "Dummy", "(ID7-ID0)"],
    ],
    source_pages=[23],
)

BMP180_COMMAND_STYLE = LogicalTable(
    header=["", "Measurement", "Control register value", "Max. conversion time"],
    rows=[
        ["", "", "(register address 0xF4)", "[ms]"],
        ["", "Temperature", "0x2E", "4.5"],
        ["", "Pressure (oss = 0)", "0x34", "4.5"],
        ["", "Pressure (oss = 1)", "0x74", "7.5"],
    ],
    source_pages=[21],
)


def test_instruction_table_detected_and_parsed():
    assert is_command_table(W25Q64_INSTRUCTION_STYLE)
    cmds = {c.name: c for c in parse_command_table(W25Q64_INSTRUCTION_STYLE)}
    assert cmds["Write Enable"].opcode == "0x06"
    assert cmds["Write Enable"].data_direction == "none"
    read = cmds["Read Data"]
    assert (read.opcode, read.address_bytes, read.data_direction) == ("0x03", 3, "read")
    assert cmds["Page Program"].data_direction == "write"
    assert "Number of Clock(1-1-1)" not in cmds  # clock rows are not commands
    # dummy bytes are recorded, cycles never guessed
    assert cmds["Release Power-down / ID"].dummy_cycles is None
    assert "3 dummy byte(s)" in cmds["Release Power-down / ID"].description


def test_measurement_command_table_detected():
    assert is_command_table(BMP180_COMMAND_STYLE)
    cmds = {c.name: c.opcode for c in parse_command_table(BMP180_COMMAND_STYLE)}
    assert cmds["Temperature"] == "0x2E"
    assert cmds["Pressure (oss = 0)"] == "0x34"


def test_register_tables_are_not_command_tables():
    assert not is_command_table(BME280_STATUS_STYLE)
    assert not is_command_table(ESP32_SUMMARY_STYLE)


# --- canonical schema stays valid ----------------------------------------------

def test_schema_validates_canonical_output():
    import jsonschema

    schema = json.load(open(SCHEMA_PATH, encoding="utf-8"))
    good = {
        "peripheral": "I2C0",
        "chip": "ESP32",
        "registers": [{
            "name": "I2C_CTR_REG", "offset": "0x0004", "reset_value": "0x00",
            "access": "RW",
            "fields": [{"name": "trans_start", "bits": "[5:5]", "description": ""}],
            "confidence": "high", "source_pages": [401],
        }],
        "commands": [{
            "name": "Write Enable", "opcode": "0x06", "description": "",
            "address_bytes": None, "dummy_cycles": None,
            "data_direction": "none", "source_pages": [23],
        }],
        "extraction_confidence": "high",
        "source_pages": [401],
        "warnings": [],
        "low_confidence_pages": [],
    }
    jsonschema.validate(good, schema)

    bad_cmd = dict(good, commands=[dict(good["commands"][0], opcode="06h")])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad_cmd, schema)

    bad = dict(good, registers=[dict(good["registers"][0], offset="4")])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
