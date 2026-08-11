"""V1.7 piece 5: generation with both maps. The worker prompt gains an MCU
CONFIGURATION section (clock/GPIO/peripheral bring-up) when an MCU map is
supplied; without one, behaviour is unchanged. Deterministic — no LLM calls."""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from generation.router import route
from generation.worker import (
    SEQUENCE_UNVERIFIED_COMMENT,
    build_worker_prompt,
)

DEVICE_MAP = {
    "peripheral": "I2C", "chip": "BME280",
    "provenance": {"chip": "user", "peripheral": "user"}, "base_address": None,
    "registers": [{"name": "CHIP_ID", "offset": "0xD0", "fields": [],
                   "source_pages": [1]}],
    "commands": [], "warnings": [],
}

MCU_MAP = {
    "mcu_family": "STM32F4", "variant": "STM32F42xxx",
    "reference_manual": "rm0090.pdf", "rm_revision": "RM0090 Rev 19",
    "peripheral": "I2C",
    "sections": {"clock": [161, 212], "gpio": [281, 288], "peripheral": [860, 872]},
    "clock_enables": [
        {"peripheral": "I2C1", "bus": "APB1", "register": "RCC_APB1ENR",
         "bit": 21, "confidence": "high", "source_pages": [184]},
        {"peripheral": "GPIOB", "bus": "AHB1", "register": "RCC_AHB1ENR",
         "bit": 1, "confidence": "high", "source_pages": [181]},
    ],
    "reset_controls": [],
    "clock_registers": [],
    "gpio_registers": [
        {"name": "GPIOx_MODER", "offset": "0x00", "source_pages": [281], "fields": []},
        {"name": "GPIOx_AFRL", "offset": "0x20", "source_pages": [285], "fields": []},
    ],
    "peripheral_registers": [
        {"name": "I2C_CR1", "offset": "0x00", "source_pages": [860],
         "fields": [{"name": "PE", "bits": "[0:0]"}, {"name": "START", "bits": "[8:8]"}]},
        {"name": "I2C_SR1", "offset": "0x14", "source_pages": [866],
         "fields": [{"name": "BERR", "bits": "[8:8]"}, {"name": "AF", "bits": "[10:10]"}]},
    ],
    "extraction_confidence": "high",
}


def _prompt(mcu_map):
    d = route(DEVICE_MAP, "stm32", log=False)
    return build_worker_prompt(DEVICE_MAP, d, "stm32", mcu_map=mcu_map)


def test_no_mcu_map_no_mcu_section():
    p = _prompt(None)
    assert "MCU CONFIGURATION" not in p


def test_mcu_section_carries_clock_enable_bit():
    p = _prompt(MCU_MAP)
    assert "MCU CONFIGURATION" in p
    # the exact clock cross-check datum must reach the worker
    assert '"peripheral":"I2C1"' in p and '"register":"RCC_APB1ENR"' in p
    assert '"bit":21' in p
    # GPIO port clock enable too
    assert '"peripheral":"GPIOB"' in p


def test_mcu_section_lists_gpio_and_peripheral_registers():
    p = _prompt(MCU_MAP)
    assert "GPIOx_AFRL" in p and "GPIOx_MODER" in p
    assert "I2C_CR1" in p and "I2C_SR1" in p
    assert "BERR" in p  # error flags for item 7


def test_mcu_section_marks_pins_as_user_input():
    p = _prompt(MCU_MAP)
    assert "USER INPUT" in p
    # pins/AF exposed as concrete-valued defines, never an undefined symbol
    assert "SCL_PIN 6" in p and "undefined symbol" in p


def test_mcu_section_requires_sequence_unverified_marker():
    p = _prompt(MCU_MAP)
    assert SEQUENCE_UNVERIFIED_COMMENT in p


def test_target_toolchain_named():
    assert "arm-none-eabi-gcc" in _prompt(MCU_MAP)


def test_retry_echoes_prior_file_for_targeted_edit():
    from generation.worker import build_worker_prompt
    d = route(DEVICE_MAP, "stm32", log=False)
    prior = {"bme280_driver.c": "int foo(void){ return BAD; }"}
    p = build_worker_prompt(
        DEVICE_MAP, d, "stm32",
        feedback="- [compile] bme280_driver.c: 'BAD' undeclared", prior_files=prior)
    assert "PREVIOUS bme280_driver.c" in p
    assert "int foo(void){ return BAD; }" in p
    assert "minimal edits" in p


def test_echo_gated_on_large_window_provider():
    from generation.worker import generate_driver

    class _Spy:
        def __init__(self, large):
            self.name = "spy"
            self.large_window = large
            self.prompt = ""

        def complete_json(self, system, user):
            self.prompt = user
            return {"header_c": "h", "source_c": "s", "example_c": "e"}

    d = route(DEVICE_MAP, "stm32", log=False)
    prior = {"bme280_driver.c": "CODE_MARKER_XYZ"}
    fb = "- [compile] bme280_driver.c: boom"

    big = _Spy(True)
    generate_driver(big, DEVICE_MAP, d, "stm32", feedback=fb, prior_files=prior)
    assert "CODE_MARKER_XYZ" in big.prompt  # large window -> echoes prior code

    small = _Spy(False)
    generate_driver(small, DEVICE_MAP, d, "stm32", feedback=fb, prior_files=prior)
    assert "CODE_MARKER_XYZ" not in small.prompt  # small window -> cold re-roll


def test_prompt_stays_within_a_sane_size():
    # both maps in one prompt — guard against a blow-up past the free-tier window.
    # ~8000 chars is comfortably inside a single-shot budget for this shape.
    p = _prompt(MCU_MAP)
    assert len(p) < 8000, len(p)
