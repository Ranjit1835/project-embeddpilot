"""V1.7 piece 3: MCU ingestion — merge (table offsets + prose bit fields) and
the section-targeted ingest_mcu path. Merge logic is unit-tested; ingest_mcu is
smoke-tested against the real RM0090 when present."""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from ingestion.prose import merge_prose_fields
from ingestion.registers import ExtractedField, ExtractedRegister


def _reg(name, offset="", fields=None, reset=None):
    return ExtractedRegister(
        name=name, offset=offset, reset_value=reset,
        fields=fields or [], source_pages=[1],
    )


def test_merge_prose_fields_override_table_names():
    # table has the offset + reversed bit names; prose has clean names
    table = [_reg("RCC_ APB1ENR", offset="0x40",
                  fields=[ExtractedField("NE1C2I", "[21:21]")])]  # reversed junk
    prose = [_reg("RCC_APB1ENR",
                  fields=[ExtractedField("I2C1EN", "[21:21]", "I2C1 clock enable")])]
    out = merge_prose_fields(table, prose)
    assert len(out) == 1
    r = out[0]
    assert r.offset == "0x40"              # offset kept from the table
    assert r.name == "RCC_APB1ENR"         # clean prose name wins
    assert [f.name for f in r.fields] == ["I2C1EN"]  # prose fields win
    assert r.confidence == "high"


def test_merge_matches_across_prefix_difference():
    # 'APB1ENR' (table) and 'RCC_APB1ENR' (prose) are the same register
    table = [_reg("APB1ENR", offset="0x40")]
    prose = [_reg("RCC_APB1ENR", fields=[ExtractedField("I2C1EN", "[21:21]")])]
    out = merge_prose_fields(table, prose)
    assert len(out) == 1 and out[0].offset == "0x40"
    assert out[0].fields[0].name == "I2C1EN"


def test_merge_keeps_prose_only_and_table_only():
    table = [_reg("I2C_CCR", offset="0x1C")]                 # table-only
    prose = [_reg("I2C_FLTR", offset="0x24",
                  fields=[ExtractedField("DNF", "[3:0]")])]   # prose-only
    out = merge_prose_fields(table, prose)
    names = {r.name for r in out}
    assert names == {"I2C_CCR", "I2C_FLTR"}


def test_merge_fills_missing_offset_from_prose():
    table = [_reg("I2C_SR1", offset="")]  # table lacked an offset
    prose = [_reg("I2C_SR1", offset="0x14",
                  fields=[ExtractedField("BERR", "[8:8]")])]
    out = merge_prose_fields(table, prose)
    assert out[0].offset == "0x14"


# --- real-RM smoke test ---------------------------------------------------------

RM = os.path.join(PROJECT_ROOT, "extraction", "input", "rm0090.pdf")


@pytest.mark.skipif(not os.path.exists(RM), reason="RM0090 PDF not present")
def test_ingest_mcu_real_rm_i2c1():
    from ingestion.mcu_pipeline import ingest_mcu

    m = ingest_mcu(RM, peripheral="I2C", variant="STM32F42xxx")
    assert m["sections"]["clock"] and m["sections"]["peripheral"]

    def find(regs, key):
        return next((r for r in regs if key in r["name"].upper()), None)

    apb1 = find(m["clock_registers"], "APB1ENR")
    assert apb1 and apb1["offset"] == "0x40"
    assert apb1["name"] == "RCC_APB1ENR"  # clean name, no stray space
    i2c1en = next((f for f in apb1["fields"] if f["name"] == "I2C1EN"), None)
    assert i2c1en and i2c1en["bits"] == "[21:21]"

    sr1 = find(m["peripheral_registers"], "SR1")
    flags = {f["name"] for f in sr1["fields"]}
    assert {"BERR", "ARLO", "AF", "OVR"} <= flags

    assert find(m["gpio_registers"], "AFRL") is not None
