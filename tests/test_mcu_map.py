"""V1.7 piece 4: MCU-map schema, clock-enable derivation, and per-MCU cache.

Derivation, schema validity, and cache round-trip are unit-tested; build_mcu_map
is smoke-tested against the real RM0090 when present."""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from ingestion.mcu_cache import cache_path, get_mcu_map, load_cached, save_cached
from ingestion.mcu_pipeline import (
    MCU_SCHEMA_PATH,
    _derive_clock_controls,
    _validate_mcu_map,
)


# --- clock-enable derivation ----------------------------------------------------

CLOCK_REGS = [
    {"name": "RCC_APB1ENR", "offset": "0x40", "confidence": "high",
     "source_pages": [184], "fields": [
         {"name": "I2C1EN", "bits": "[21:21]"},
         {"name": "I2C2EN", "bits": "[22:22]"},
         {"name": "TIM2EN", "bits": "[0:0]"}]},
    {"name": "RCC_AHB1ENR", "offset": "0x30", "confidence": "high",
     "source_pages": [181], "fields": [{"name": "GPIOAEN", "bits": "[0:0]"}]},
    {"name": "RCC_APB1RSTR", "offset": "0x20", "confidence": "high",
     "source_pages": [174], "fields": [{"name": "I2C1RST", "bits": "[21:21]"}]},
    {"name": "RCC_APB1LPENR", "offset": "0x60", "confidence": "high",
     "source_pages": [193], "fields": [{"name": "I2C1LPEN", "bits": "[21:21]"}]},
]


def test_derive_clock_enable_maps_peripheral_bus_register_bit():
    enables, resets = _derive_clock_controls(CLOCK_REGS)
    i2c1 = next(c for c in enables if c["peripheral"] == "I2C1")
    assert (i2c1["bus"], i2c1["register"], i2c1["bit"]) == ("APB1", "RCC_APB1ENR", 21)
    gpioa = next(c for c in enables if c["peripheral"] == "GPIOA")
    assert (gpioa["bus"], gpioa["bit"]) == ("AHB1", 0)


def test_derive_reset_controls():
    _enables, resets = _derive_clock_controls(CLOCK_REGS)
    i2c1 = next(c for c in resets if c["peripheral"] == "I2C1")
    assert (i2c1["bus"], i2c1["register"], i2c1["bit"]) == ("APB1", "RCC_APB1RSTR", 21)


def test_lpenr_registers_excluded_from_clock_enables():
    # RCC_APB1LPENR is low-power gating, not the enable bit that matters
    enables, _ = _derive_clock_controls(CLOCK_REGS)
    assert not any(c["register"].endswith("LPENR") for c in enables)
    assert not any(c["peripheral"] == "I2C1LP" for c in enables)


# --- schema validity ------------------------------------------------------------

def _minimal_valid_map():
    enables, _ = _derive_clock_controls(CLOCK_REGS)
    return {
        "mcu_family": "STM32F4", "variant": "STM32F42xxx",
        "reference_manual": "rm0090.pdf", "rm_revision": "RM0090 Rev 19",
        "peripheral": "I2C",
        "sections": {"clock": [161, 212], "gpio": [281, 288], "peripheral": [860, 872]},
        "clock_enables": enables, "reset_controls": [],
        "clock_registers": CLOCK_REGS, "gpio_registers": [],
        "peripheral_registers": [{"name": "I2C_CR1", "offset": "0x00",
                                  "source_pages": [860], "fields": []}],
        "extraction_confidence": "high",
    }


def test_schema_file_is_valid_json():
    with open(MCU_SCHEMA_PATH, encoding="utf-8") as f:
        json.load(f)


def test_minimal_map_validates():
    _validate_mcu_map(_minimal_valid_map())  # must not raise


def test_bad_clock_enable_bit_rejected():
    import jsonschema

    m = _minimal_valid_map()
    m["clock_enables"][0]["bit"] = 99  # out of 0..31
    with pytest.raises(jsonschema.exceptions.ValidationError):
        _validate_mcu_map(m)


# --- cache ----------------------------------------------------------------------

def test_cache_round_trip(tmp_path):
    m = _minimal_valid_map()
    path = save_cached(m, cache_dir=str(tmp_path))
    assert os.path.exists(path)
    loaded = load_cached("STM32F4", "STM32F42xxx", "I2C", cache_dir=str(tmp_path))
    assert loaded == m


def test_cache_key_is_variant_specific(tmp_path):
    p1 = cache_path("STM32F4", "STM32F42xxx", "I2C", cache_dir=str(tmp_path))
    p2 = cache_path("STM32F4", "STM32F405", "I2C", cache_dir=str(tmp_path))
    p3 = cache_path("STM32F4", "STM32F42xxx", "SPI", cache_dir=str(tmp_path))
    assert p1 != p2 and p1 != p3  # variant AND peripheral partition the cache


def test_get_mcu_map_uses_cache(tmp_path, monkeypatch):
    import ingestion.mcu_cache as mc

    calls = {"n": 0}

    def fake_build(pdf_path, peripheral="I2C", variant=None):
        calls["n"] += 1
        m = _minimal_valid_map()
        m["variant"] = variant
        m["peripheral"] = peripheral
        return m

    monkeypatch.setattr(mc, "build_mcu_map", fake_build)
    a = mc.get_mcu_map("x.pdf", "I2C", "STM32F42xxx", cache_dir=str(tmp_path))
    b = mc.get_mcu_map("x.pdf", "I2C", "STM32F42xxx", cache_dir=str(tmp_path))
    assert a == b
    assert calls["n"] == 1  # second call served from cache, no rebuild


# --- real-RM smoke --------------------------------------------------------------

RM = os.path.join(PROJECT_ROOT, "extraction", "input", "rm0090.pdf")


@pytest.mark.skipif(not os.path.exists(RM), reason="RM0090 PDF not present")
def test_build_mcu_map_real_rm():
    from ingestion.mcu_pipeline import build_mcu_map

    m = build_mcu_map(RM, peripheral="I2C", variant="STM32F42xxx")
    _validate_mcu_map(m)
    assert m["extraction_confidence"] == "high"
    assert m["rm_revision"] and "RM0090" in m["rm_revision"]
    i2c1 = next(c for c in m["clock_enables"] if c["peripheral"].upper() == "I2C1")
    assert (i2c1["bus"], i2c1["bit"]) == ("APB1", 21)
