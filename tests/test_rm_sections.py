"""V1.7: MCU reference-manual section locator.

Pure range/matching logic is unit-tested; read_outline is smoke-tested against
the real RM0090 only when the PDF is present (skipped in CI otherwise)."""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from ingestion.rm_sections import (
    build_sections,
    find_section,
    peripheral_pages,
    read_outline,
)

# (level, title, page) — a slice of an RM0090-shaped outline incl. the RCC split
OUTLINE = [
    (1, "6 Reset and clock control for STM32F42xxx and STM32F43xxx (RCC)", 150),
    (2, "6.3 RCC registers", 161),
    (3, "6.3.13 RCC APB1 peripheral clock enable register (RCC_APB1ENR)", 183),
    (1, "7 Reset and clock control for STM32F405/07 (RCC)", 220),
    (1, "8 General-purpose I/Os (GPIO)", 267),
    (2, "8.4 GPIO registers", 281),
    (1, "27 Inter-integrated circuit (I2C) interface", 839),
    (2, "27.6 I2C registers", 860),
    (1, "28 Universal synchronous asynchronous receiver (USART)", 960),
]


def test_build_sections_computes_end_pages():
    secs = build_sections(OUTLINE)
    gpio = find_section(secs, r"General-purpose I/?Os")
    assert gpio.start_page == 267
    assert gpio.end_page == 838   # ends just before ch27 (I2C) at 839


def test_subsection_end_is_bounded_by_next_sibling_or_higher():
    secs = build_sections(OUTLINE)
    apb1 = find_section(secs, r"RCC_APB1ENR")
    # L3 section ends before the next entry at level <= 3 (ch7 at 220)
    assert (apb1.start_page, apb1.end_page) == (183, 219)


def test_variant_pins_the_right_rcc_chapter():
    secs = build_sections(OUTLINE)
    f42 = find_section(secs, r"\(RCC\)|Reset and clock", variant="STM32F42xxx")
    assert f42.start_page == 150
    f405 = find_section(secs, r"\(RCC\)|Reset and clock", variant="STM32F405")
    assert f405.start_page == 220


def test_peripheral_pages_word_boundary():
    secs = build_sections(OUTLINE)
    assert peripheral_pages(secs, "I2C") == (839, 959)
    # a peripheral not present -> None (does not partial-match)
    assert peripheral_pages(secs, "SPI") is None


def test_unresolved_pages_are_skipped():
    secs = build_sections([(1, "Ghost", None), (1, "Real", 5), (1, "Next", 9)])
    assert [s.title for s in secs] == ["Real", "Next"]
    assert find_section(secs, "Real").end_page == 8


def test_find_section_absent_returns_none():
    assert find_section(build_sections(OUTLINE), r"\bCAN\b") is None


# --- real-RM smoke test (skips without the PDF) ---------------------------------

RM = os.path.join(PROJECT_ROOT, "extraction", "input", "rm0090.pdf")


@pytest.mark.skipif(not os.path.exists(RM), reason="RM0090 PDF not present")
def test_read_outline_locates_rcc_gpio_i2c_in_real_rm():
    secs = read_outline(RM)
    assert len(secs) > 1000
    rcc = find_section(secs, r"\(RCC\)", variant="STM32F42xxx")
    gpio = find_section(secs, r"General-purpose I/?Os")
    i2c = find_section(secs, r"Inter-integrated circuit")
    assert rcc and gpio and i2c
    # RCC_APB1ENR (holds I2C1EN) sits inside the RCC chapter range
    apb1 = find_section(secs, r"RCC_APB1ENR")
    assert apb1 is not None and apb1.start_page >= rcc.start_page
    assert gpio.start_page < i2c.start_page
