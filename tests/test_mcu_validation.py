"""V1.7 piece 6: MCU cross-check (clock/GPIO/peripheral bit + offset vs the MCU
map) and the reference-manual sequence-UNVERIFIED marker."""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from validator.crosscheck import SEQUENCE_MARKER, scan_unverified_computations
from validator.mcu_crosscheck import mcu_crosscheck
from validator.report import ValidationReport

MCU_MAP = {
    "mcu_family": "STM32F4", "peripheral": "I2C",
    "clock_enables": [
        {"peripheral": "I2C1", "bus": "APB1", "register": "RCC_APB1ENR", "bit": 21,
         "source_pages": [184]},
        {"peripheral": "GPIOB", "bus": "AHB1", "register": "RCC_AHB1ENR", "bit": 1,
         "source_pages": [181]},
    ],
    "reset_controls": [],
    "clock_registers": [
        {"name": "RCC_APB1ENR", "offset": "0x40", "source_pages": [183], "fields": []}],
    "gpio_registers": [
        {"name": "GPIOx_AFRL", "offset": "0x20", "source_pages": [285], "fields": []}],
    "peripheral_registers": [
        {"name": "I2C_CR1", "offset": "0x00", "source_pages": [860],
         "fields": [{"name": "PE", "bits": "[0:0]"}]},
        {"name": "I2C_SR1", "offset": "0x14", "source_pages": [866],
         "fields": [{"name": "BERR", "bits": "[8:8]"}]}],
}


def _check(src: str):
    report = ValidationReport()
    mcu_crosscheck({"drv.c": src.splitlines()}, MCU_MAP, report)
    return report


def test_correct_clock_bit_passes():
    r = _check("#define RCC_APB1ENR_I2C1EN_Pos 21\n")
    assert r.checks["mcu_crosscheck"] == "pass"
    assert not r.failures


def test_correct_clock_bit_as_shift_mask_passes():
    r = _check("#define RCC_APB1ENR_I2C1EN (1U << 21)\n")
    assert r.checks["mcu_crosscheck"] == "pass"


def test_wrong_clock_bit_hard_fails():
    # bit 22 is I2C2, not I2C1 -> enabling the wrong peripheral's clock
    r = _check("#define RCC_APB1ENR_I2C1EN_Pos 22\n")
    assert r.checks["mcu_crosscheck"] == "fail"
    assert any("wrong clock/peripheral bit" in f.message for f in r.failures)


def test_wrong_register_offset_hard_fails():
    r = _check("#define I2C_CR1_OFFSET 0x04\n")  # map says 0x00
    assert r.checks["mcu_crosscheck"] == "fail"
    assert any("does not match MCU-map offset" in f.message for f in r.failures)


def test_correct_offset_and_field_bit_pass():
    src = ("#define I2C_CR1_OFFSET 0x00\n"
           "#define I2C_SR1_BERR_Pos 8\n")
    r = _check(src)
    assert r.checks["mcu_crosscheck"] == "pass"


def test_unresolvable_cmsis_symbols_are_skipped_not_failed():
    # no named map-derived defines -> nothing to check, but not a failure
    r = _check("RCC->APB1ENR |= RCC_APB1ENR_I2C1EN;\n")
    assert r.checks["mcu_crosscheck"] == "skipped"
    assert not r.failures


def test_sequence_marker_recorded_as_unverified():
    report = ValidationReport()
    src = (f"/* {SEQUENCE_MARKER} — see RM 27.3.3 */\n"
           "void i2c_init(void) { }\n")
    scan_unverified_computations({"drv.c": src.splitlines()}, report)
    report.checks["compile"] = "pass"
    report.checks["register_crosscheck"] = "pass"
    report.finalize()
    assert report.unverified_computations
    assert report.status == "validated-with-unverified-fields"
