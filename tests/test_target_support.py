"""The target gate: an unsupported MCU is refused, never approximated.

Regression cover for a live production bug — a requirement naming an ESP32
(Xtensa, not ARM) was accepted with zero blocking questions, built as an
STM32F4, shipped with an stm32f4.ld linker script inside it, emulated on an
STM32F4 platform and reported `working-emulated`.
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from orchestration.targets import (
    SUPPORTED_LABEL,
    UnsupportedTargetError,
    assert_target_supported,
    is_supported_mcu,
    supported_targets,
)


# --- what the firmware path can genuinely build ----------------------------------

@pytest.mark.parametrize("mcu", [
    "STM32F411RET6",
    "STM32F407VGT6",
    "stm32f429zi",
    "STM32F446RE",
    "STM32F4-11RE",      # separators are noise
    "  STM32F411RET6 ",  # and so is surrounding whitespace
])
def test_stm32f4_parts_are_supported(mcu):
    assert is_supported_mcu(mcu)
    assert_target_supported(mcu)  # must not raise


# --- what it must refuse ----------------------------------------------------------

@pytest.mark.parametrize("mcu", [
    "ESP32",              # the live bug: Xtensa, not even ARM
    "ESP32-WROOM-32",
    "STM32F103C8T6",      # Cortex-M3 — -mcpu=cortex-m4 alone would be wrong
    "STM32H743ZI",        # different family, different peripheral layout
    "nRF52840",
    "RP2040",
    "ATmega328P",
    "MSP430F5529",
])
def test_other_parts_are_refused(mcu):
    assert not is_supported_mcu(mcu)
    with pytest.raises(UnsupportedTargetError):
        assert_target_supported(mcu)


@pytest.mark.parametrize("mcu", [None, "", "   "])
def test_an_unknown_target_is_refused_not_assumed(mcu):
    """Absence of evidence that a part is wrong is not evidence it is right.
    Defaulting to 'build it anyway' is how the ESP32 run went green."""
    assert not is_supported_mcu(mcu)
    with pytest.raises(UnsupportedTargetError):
        assert_target_supported(mcu)


# --- the refusal has to be usable -------------------------------------------------

def test_refusal_names_the_part_that_was_asked_for():
    with pytest.raises(UnsupportedTargetError) as exc:
        assert_target_supported("ESP32", board="ESP32-WROOM-32 devkit")
    message = str(exc.value)
    assert "ESP32" in message
    assert "ESP32-WROOM-32 devkit" in message, "board should be echoed as context"
    assert "STM32F4" in message, "must say what IS supported, not just what is not"
    assert exc.value.requested == "ESP32"


def test_refusal_explains_why_rather_than_only_refusing():
    with pytest.raises(UnsupportedTargetError) as exc:
        assert_target_supported("RP2040")
    message = str(exc.value).lower()
    assert "linker" in message or "scaffold" in message or "emulator" in message


def test_a_near_miss_part_number_is_not_rounded_up():
    """'STM32F4' alone is a family, not a part, and 'STM32F1' is a different
    core. Neither may be nudged into the supported set."""
    assert not is_supported_mcu("STM32F4")
    assert not is_supported_mcu("STM32F1")


# --- capabilities reporting -------------------------------------------------------

def test_supported_targets_states_the_consequence():
    caps = supported_targets()
    assert caps["mcu_families"] == ["STM32F4"]
    assert caps["label"] == SUPPORTED_LABEL
    assert "refused" in caps["consequence"].lower()
