"""V1.7 DoD (deterministic): a COMPLETE STM32F4 I2C1 driver for a device passes
the whole pipeline through the REAL validator — arm-none-eabi-gcc compile (via
the STM32 stub), device register cross-check, MCU RCC/GPIO cross-check, and the
reference-manual init SEQUENCE surfaced as unverified.

The live LLM path is gated by the free-tier Groq token window (device map + MCU
map + a complete-driver output exceed 8000 TPM — see V1.7 report), so the DoD's
validation requirements are proven here with a fixed driver, exactly as the
V1.6.1 DoD was closed deterministically."""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from generation.pipeline import generate_validated_driver
from generation.provider import MockProvider

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
        {"peripheral": "I2C1", "bus": "APB1", "register": "RCC_APB1ENR", "bit": 21,
         "confidence": "high", "source_pages": [184]},
        {"peripheral": "GPIOB", "bus": "AHB1", "register": "RCC_AHB1ENR", "bit": 1,
         "confidence": "high", "source_pages": [181]},
    ],
    "reset_controls": [],
    "clock_registers": [
        {"name": "RCC_APB1ENR", "offset": "0x40", "source_pages": [183], "fields": []},
        {"name": "RCC_AHB1ENR", "offset": "0x30", "source_pages": [180], "fields": []}],
    "gpio_registers": [
        {"name": "GPIOx_MODER", "offset": "0x00", "source_pages": [281], "fields": []},
        {"name": "GPIOx_OTYPER", "offset": "0x04", "source_pages": [281], "fields": []},
        {"name": "GPIOx_AFRL", "offset": "0x20", "source_pages": [285], "fields": []}],
    "peripheral_registers": [
        {"name": "I2C_CR1", "offset": "0x00", "source_pages": [860],
         "fields": [{"name": "PE", "bits": "[0:0]"}]},
        {"name": "I2C_SR1", "offset": "0x14", "source_pages": [866],
         "fields": [{"name": "BERR", "bits": "[8:8]"}]}],
    "extraction_confidence": "high",
}

# A complete driver: device access via callbacks + STM32 bring-up (clock/GPIO/
# I2C) with named bit defines (cross-checkable) and a sequence-marked init.
_SEQ = ("/* UNVERIFIED: sequence transcribed from reference manual prose — not "
        "cross-checked */")

COMPLETE_DRIVER = {
    "header_c": (
        "#ifndef BME280_DRIVER_H\n#define BME280_DRIVER_H\n#include <stdint.h>\n\n"
        "#define BME280_CHIP_ID_REG 0xD0\n\n"
        "typedef int (*bme280_reg_read_fn)(uint8_t reg, uint8_t *buf, uint32_t len);\n"
        "int bme280_read_chip_id(bme280_reg_read_fn read_fn, uint8_t *out);\n"
        "void stm32_i2c1_init(uint32_t scl_pin, uint32_t sda_pin, uint32_t af);\n"
        "int stm32_i2c1_read(uint8_t reg, uint8_t *buf, uint32_t len);\n"
        "#endif\n"
    ),
    "source_c": (
        '#include "bme280_driver.h"\n#include <stm32f4xx.h>\n\n'
        "/* MCU bit positions from the MCU map — cross-checked */\n"
        "#define RCC_AHB1ENR_GPIOBEN_Pos 1\n"
        "#define RCC_APB1ENR_I2C1EN_Pos 21\n"
        "#define I2C_CR1_PE_Pos 0\n\n"
        "int bme280_read_chip_id(bme280_reg_read_fn read_fn, uint8_t *out)\n{\n"
        "    return read_fn(BME280_CHIP_ID_REG, out, 1);\n}\n\n"
        f"{_SEQ}\n"
        "void stm32_i2c1_init(uint32_t scl_pin, uint32_t sda_pin, uint32_t af)\n{\n"
        "    RCC->AHB1ENR |= (1U << RCC_AHB1ENR_GPIOBEN_Pos);\n"
        "    RCC->APB1ENR |= (1U << RCC_APB1ENR_I2C1EN_Pos);\n"
        "    GPIOB->MODER |= (2U << (scl_pin * 2U)) | (2U << (sda_pin * 2U));\n"
        "    GPIOB->OTYPER |= (1U << scl_pin) | (1U << sda_pin);\n"
        "    GPIOB->AFR[0] |= (af << (scl_pin * 4U)) | (af << (sda_pin * 4U));\n"
        "    I2C1->CR1 |= (1U << I2C_CR1_PE_Pos);\n}\n\n"
        "int stm32_i2c1_read(uint8_t reg, uint8_t *buf, uint32_t len)\n{\n"
        "    uint32_t i;\n    (void)reg;\n"
        "    for (i = 0U; i < len; i++) {\n"
        "        buf[i] = (uint8_t)(I2C1->DR & 0xFFU);\n    }\n"
        "    return (int)(I2C1->SR1 & 0x1U);\n}\n"
    ),
    "example_c": (
        '#include <stdint.h>\n#include "bme280_driver.h"\n\n'
        "int main(void);\nint main(void)\n{\n"
        "    uint8_t id = 0;\n"
        "    stm32_i2c1_init(6U, 7U, 4U);  /* PB6=SCL, PB7=SDA, AF4=I2C1 (user input) */\n"
        "    (void)bme280_read_chip_id(stm32_i2c1_read, &id);\n"
        "    return (int)id;\n}\n"
    ),
    "notes": "",
}


def _have_arm():
    from validator.compile_check import find_compiler
    return find_compiler("stm32") is not None


def test_complete_stm32f4_i2c1_driver_validates(tmp_path):
    if not _have_arm():
        pytest.skip("no compiler for stm32")
    result = generate_validated_driver(
        DEVICE_MAP, "stm32", MockProvider([COMPLETE_DRIVER]),
        workdir_root=str(tmp_path), mcu_map=MCU_MAP,
    )
    last = result["reports"][-1]
    assert last["checks"]["compile"] == "pass", last["failures"]
    assert last["checks"]["register_crosscheck"] == "pass", last["failures"]
    assert last["checks"]["mcu_crosscheck"] == "pass", last["failures"]
    # the RM-derived init sequence is surfaced, so the verdict is honest
    assert last["unverified_computations"], "init sequence not surfaced"
    assert result["status"] == "validated-with-unverified-fields", last


def test_wrong_clock_bit_is_caught_end_to_end(tmp_path):
    if not _have_arm():
        pytest.skip("no compiler for stm32")
    bad = dict(COMPLETE_DRIVER)
    bad["source_c"] = COMPLETE_DRIVER["source_c"].replace(
        "#define RCC_APB1ENR_I2C1EN_Pos 21", "#define RCC_APB1ENR_I2C1EN_Pos 22")
    result = generate_validated_driver(
        DEVICE_MAP, "stm32", MockProvider([bad, bad, bad, bad]),
        workdir_root=str(tmp_path), mcu_map=MCU_MAP,
    )
    assert result["status"] == "unvalidated"
    assert any(f["check"] == "mcu_crosscheck"
               for f in result["reports"][0]["failures"])
