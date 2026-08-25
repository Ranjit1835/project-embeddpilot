"""V2 workstream 3: the system-integration cross-check (resource conflicts).

Covers each conflict class the composed system can produce — pin mux, bus
address, bus/clock contention, DMA and IRQ — plus the two ways this check must
NOT cry wolf: a clean multi-device system passes, and a system with nothing to
compose is `not_applicable`, never a failure and never "skipped".
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validator.report import ValidationReport
from validator.resource_crosscheck import build_resource_map, resource_crosscheck


def _run(devices, mcu_map=None):
    rep = ValidationReport()
    resource_crosscheck(devices, mcu_map, rep)
    return rep


def _messages(rep):
    return " | ".join(f.message for f in rep.failures)


# --- fixtures: a small composed system ---------------------------------------

def _bme280(**bus):
    return {"name": "BME280",
            "pins": [{"pin": "PB6", "function": "I2C1_SCL"},
                     {"pin": "PB7", "function": "I2C1_SDA"}],
            "bus": {"kind": "i2c", "instance": "I2C1", "address": "0x76",
                    "speed_hz": 400000, **bus}}


def _ssd1306(**bus):
    return {"name": "SSD1306",
            "pins": [{"pin": "PB6", "function": "I2C1_SCL"},
                     {"pin": "PB7", "function": "I2C1_SDA"}],
            "bus": {"kind": "i2c", "instance": "I2C1", "address": "0x3C",
                    "speed_hz": 400000, **bus}}


def _relay(pin="PB5"):
    return {"name": "Relay", "pins": [{"pin": pin, "function": "GPIO_OUT"}]}


# --- 1. pin-mux conflicts ----------------------------------------------------

def test_pin_double_booked_is_a_hard_failure():
    """The V2_PLAN's own example: PB6 as I2C1_SCL and as a GPIO output."""
    rep = _run([_bme280(), _ssd1306(), _relay(pin="PB6")])
    assert rep.checks["resource_crosscheck"] == "fail"
    msg = _messages(rep)
    assert "PB6" in msg
    # names the resource AND every claimant
    assert "I2C1_SCL" in msg and "GPIO_OUT" in msg
    assert "BME280" in msg and "SSD1306" in msg and "Relay" in msg
    assert all(f.check == "resource_crosscheck" for f in rep.failures)


def test_shared_i2c_signals_are_not_a_conflict():
    """Two I2C devices on one bus SHARE SCL/SDA — that is how I2C works. A
    checker that flagged it would be useless."""
    rep = _run([_bme280(), _ssd1306()])
    assert rep.checks["resource_crosscheck"] == "pass"
    assert not rep.failures


def test_spi_chip_selects_are_not_shareable():
    """SCK/MOSI/MISO are multi-drop; CS is not. Two devices on one CS is a real
    conflict even though they sit on the same SPI instance."""
    def flash(name, cs):
        return {"name": name,
                "pins": [{"pin": "PA5", "function": "SPI1_SCK"},
                         {"pin": "PA7", "function": "SPI1_MOSI"},
                         {"pin": cs, "function": "SPI1_NSS"}],
                "bus": {"kind": "spi", "instance": "SPI1", "speed_hz": 8000000}}

    ok = _run([flash("W25Q", "PA4"), flash("ADXL", "PA3")])
    assert ok.checks["resource_crosscheck"] == "pass"

    clash = _run([flash("W25Q", "PA4"), flash("ADXL", "PA4")])
    assert clash.checks["resource_crosscheck"] == "fail"
    assert "PA4" in _messages(clash)
    # the genuinely shared SPI lines must NOT also be reported
    assert "PA5" not in _messages(clash)


def test_unknown_bus_kind_defaults_to_conflict_not_silent_pass():
    """An unrecognised bus is not evidence that sharing is safe."""
    def node(name):
        return {"name": name, "pins": [{"pin": "PC1", "function": "XBUS1_DAT"}],
                "bus": {"kind": "xbus", "instance": "XBUS1"}}

    rep = _run([node("A"), node("B")])
    assert rep.checks["resource_crosscheck"] == "fail"
    assert "PC1" in _messages(rep)


def test_explicit_shared_declaration_is_honoured():
    a = {"name": "A", "pins": [{"pin": "PC1", "function": "XBUS1_DAT", "shared": True}],
         "bus": {"kind": "xbus", "instance": "XBUS1"}}
    b = {"name": "B", "pins": [{"pin": "PC1", "function": "XBUS1_DAT", "shared": True}],
         "bus": {"kind": "xbus", "instance": "XBUS1"}}
    assert _run([a, b]).checks["resource_crosscheck"] == "pass"


def test_explicit_exclusive_declaration_overrides_bus_topology():
    """A device that states it needs the pin exclusively is believed, even on a
    bus whose signals are normally shareable."""
    greedy = _bme280()
    greedy["pins"][0]["shared"] = False
    rep = _run([greedy, _ssd1306()])
    assert rep.checks["resource_crosscheck"] == "fail"
    assert "PB6" in _messages(rep)


def test_pin_designator_leading_zeros_normalize():
    rep = _run([{"name": "A", "pins": [{"pin": "PB06", "function": "GPIO_OUT"}]},
                {"name": "B", "pins": [{"pin": "pb6", "function": "GPIO_IN"}]}])
    assert rep.checks["resource_crosscheck"] == "fail"
    assert "PB6" in _messages(rep)


# --- 2. bus address collisions ----------------------------------------------

def test_i2c_address_collision_is_a_hard_failure():
    twin = _ssd1306()
    twin["bus"]["address"] = "0x76"          # same as the BME280
    rep = _run([_bme280(), twin])
    assert rep.checks["resource_crosscheck"] == "fail"
    msg = _messages(rep)
    assert "0x76" in msg and "I2C1" in msg
    assert "BME280" in msg and "SSD1306" in msg


def test_same_address_on_different_bus_instances_is_fine():
    other = _bme280()
    other["name"] = "BME280-B"
    other["bus"] = {"kind": "i2c", "instance": "I2C2", "address": "0x76",
                    "speed_hz": 400000}
    other["pins"] = [{"pin": "PB10", "function": "I2C2_SCL"},
                     {"pin": "PB11", "function": "I2C2_SDA"}]
    assert _run([_bme280(), other]).checks["resource_crosscheck"] == "pass"


def test_eight_bit_address_is_rejected_with_the_seven_bit_value():
    dev = _ssd1306()
    dev["bus"]["address"] = 0xEC             # 8-bit write address for 0x76
    rep = _run([_bme280(), dev])
    assert rep.checks["resource_crosscheck"] == "fail"
    assert "0xEC" in _messages(rep) and "0x76" in _messages(rep)


def test_integer_and_string_addresses_compare_equal():
    a, b = _bme280(), _ssd1306()
    a["bus"]["address"] = 0x76
    b["bus"]["address"] = "0x76"
    assert _run([a, b]).checks["resource_crosscheck"] == "fail"


# --- 3. clock / bus contention ----------------------------------------------

def test_conflicting_i2c_speeds_on_one_peripheral():
    rep = _run([_bme280(speed_hz=400000), _ssd1306(speed_hz=100000)])
    assert rep.checks["resource_crosscheck"] == "fail"
    msg = _messages(rep)
    assert "I2C1" in msg and "400000" in msg and "100000" in msg
    assert "BME280" in msg and "SSD1306" in msg


def test_conflicting_spi_mode_on_one_peripheral():
    def dev(name, cs, spi_mode):
        return {"name": name, "pins": [{"pin": cs, "function": "SPI1_NSS"}],
                "bus": {"kind": "spi", "instance": "SPI1", "spi_mode": spi_mode}}

    rep = _run([dev("A", "PA4", 0), dev("B", "PA3", 3)])
    assert rep.checks["resource_crosscheck"] == "fail"
    assert "spi_mode" in _messages(rep)


def test_one_instance_claimed_as_two_peripheral_kinds():
    a = {"name": "A", "bus": {"kind": "i2c", "instance": "PERIPH1"}}
    b = {"name": "B", "bus": {"kind": "spi", "instance": "PERIPH1"}}
    rep = _run([a, b])
    assert rep.checks["resource_crosscheck"] == "fail"
    assert "PERIPH1" in _messages(rep)


def test_undeclared_config_key_is_not_contention():
    """An undeclared value contradicts nothing — inventing a disagreement would
    be as wrong as missing a real one."""
    quiet = _ssd1306()
    quiet["bus"].pop("speed_hz")
    assert _run([_bme280(speed_hz=400000), quiet]).checks["resource_crosscheck"] == "pass"


def test_matching_bus_config_passes():
    assert _run([_bme280(speed_hz=100000),
                 _ssd1306(speed_hz=100000)]).checks["resource_crosscheck"] == "pass"


# --- 4. DMA / IRQ contention -------------------------------------------------

def test_dma_stream_collision_is_a_hard_failure():
    a = _bme280(); a["dma"] = [{"controller": "DMA1", "stream": 0, "channel": 1,
                                "direction": "rx"}]
    b = _ssd1306(); b["dma"] = [{"controller": "DMA1", "stream": 0, "channel": 7,
                                 "direction": "tx"}]
    rep = _run([a, b])
    assert rep.checks["resource_crosscheck"] == "fail"
    msg = _messages(rep)
    assert "DMA1:stream0" in msg and "BME280" in msg and "SSD1306" in msg


def test_distinct_dma_streams_do_not_collide():
    a = _bme280(); a["dma"] = [{"controller": "DMA1", "stream": 0}]
    b = _ssd1306(); b["dma"] = [{"controller": "DMA1", "stream": 5}]
    assert _run([a, b]).checks["resource_crosscheck"] == "pass"


def test_same_stream_on_different_controllers_does_not_collide():
    a = _bme280(); a["dma"] = [{"controller": "DMA1", "stream": 0}]
    b = _ssd1306(); b["dma"] = [{"controller": "DMA2", "stream": 0}]
    assert _run([a, b]).checks["resource_crosscheck"] == "pass"


def test_channel_only_parts_collide_on_channel():
    a = _bme280(); a["dma"] = [{"controller": "DMA1", "channel": 6}]
    b = _ssd1306(); b["dma"] = [{"controller": "DMA1", "channel": 6}]
    rep = _run([a, b])
    assert rep.checks["resource_crosscheck"] == "fail"
    assert "DMA1:channel6" in _messages(rep)


def test_irq_line_collision_is_a_hard_failure():
    a = _relay("PB5"); a["irq"] = ["EXTI9_5"]
    b = {"name": "Button", "pins": [{"pin": "PA0", "function": "GPIO_IN"}],
         "irq": ["EXTI9_5"]}
    rep = _run([a, b])
    assert rep.checks["resource_crosscheck"] == "fail"
    msg = _messages(rep)
    assert "EXTI9_5" in msg and "Relay" in msg and "Button" in msg


def test_peripheral_own_irq_shared_by_devices_on_that_bus_is_fine():
    """Both I2C1 devices claim I2C1_EV_IRQn — that is the peripheral's own
    interrupt, not two drivers fighting over a vector."""
    a = _bme280(); a["irq"] = ["I2C1_EV_IRQn"]
    b = _ssd1306(); b["irq"] = ["I2C1_EV_IRQn"]
    assert _run([a, b]).checks["resource_crosscheck"] == "pass"


def test_shared_irq_can_be_declared_explicitly():
    a = _relay("PB5"); a["irq"] = [{"line": "EXTI9_5", "shared": True}]
    b = {"name": "Button", "irq": [{"line": "EXTI9_5", "shared": True}]}
    assert _run([a, b]).checks["resource_crosscheck"] == "pass"


# --- clean system + reporting -----------------------------------------------

def test_clean_multi_device_configuration_passes():
    a = _bme280(); a["dma"] = [{"controller": "DMA1", "stream": 0}]
    a["irq"] = ["I2C1_EV_IRQn"]
    b = _ssd1306(); b["dma"] = [{"controller": "DMA1", "stream": 6}]
    b["irq"] = ["I2C1_EV_IRQn"]
    rep = _run([a, b, _relay("PB5")])
    assert rep.checks["resource_crosscheck"] == "pass"
    assert not rep.failures
    assert any("no pin-mux" in n for n in rep.notes)


def test_a_conflict_fails_the_overall_verdict():
    rep = ValidationReport()
    rep.checks["compile"] = "pass"
    rep.checks["register_crosscheck"] = "pass"
    resource_crosscheck([_bme280(), _relay("PB6")], {}, rep)
    rep.finalize()
    assert rep.status == "failed"


def test_every_conflict_is_reported_not_just_the_first():
    a = _bme280()
    b = _ssd1306(speed_hz=100000)
    b["bus"]["address"] = "0x76"                       # + address collision
    a["dma"] = [{"controller": "DMA1", "stream": 0}]
    b["dma"] = [{"controller": "DMA1", "stream": 0}]   # + DMA collision
    rep = _run([a, b, _relay("PB6")])                  # + pin collision
    kinds = _messages(rep)
    assert "PB6" in kinds and "0x76" in kinds and "speed_hz" in kinds \
        and "DMA1:stream0" in kinds
    assert len(rep.failures) >= 4


# --- not_applicable: nothing to compose is NOT a failure ---------------------

def test_single_device_is_not_applicable():
    rep = _run([_bme280()])
    assert rep.checks["resource_crosscheck"] == "not_applicable"
    assert not rep.failures


def test_no_devices_is_not_applicable():
    for empty in ([], None):
        rep = _run(empty)
        assert rep.checks["resource_crosscheck"] == "not_applicable"
        assert not rep.failures


def test_devices_without_resource_data_is_not_applicable():
    rep = _run([{"name": "A"}, {"name": "B"}])
    assert rep.checks["resource_crosscheck"] == "not_applicable"
    assert not rep.failures
    assert any("no pin/bus/DMA/IRQ claims" in n for n in rep.notes)


def test_not_applicable_is_distinct_from_skipped():
    """This check needs no toolchain, so it never degrades to 'skipped' — and
    'nothing to check' must never be dressed up as 'checked'."""
    rep = _run([_bme280()])
    assert rep.checks["resource_crosscheck"] not in ("skipped", "pass", "fail")


# --- honesty about the MCU data we do NOT have -------------------------------

def test_pin_capability_is_declared_unverified_without_an_af_table():
    rep = _run([_bme280(), _ssd1306()])
    assert rep.checks["resource_crosscheck"] == "pass"
    note = " ".join(rep.notes)
    assert "pin alternate-function capability was NOT verified" in note
    assert "not guessed" in note


def test_af_table_when_supplied_catches_an_impossible_pin_function():
    mcu_map = {"mcu_family": "STM32F4", "variant": "STM32F411",
               "pin_alternate_functions": {
                   "PB6": [{"af": 4, "signal": "I2C1_SCL"},
                           {"af": 2, "signal": "TIM4_CH1"}],
                   "PB7": [{"af": 4, "signal": "I2C1_SDA"}],
                   "PA2": [{"af": 7, "signal": "USART2_TX"}]}}
    bad = _ssd1306()
    bad["pins"] = [{"pin": "PA2", "function": "I2C1_SCL"},
                   {"pin": "PB7", "function": "I2C1_SDA"}]
    rep = _run([_bme280(), bad], mcu_map)
    assert rep.checks["resource_crosscheck"] == "fail"
    msg = _messages(rep)
    assert "PA2" in msg and "I2C1_SCL" in msg and "USART2_TX" in msg


def test_af_table_when_supplied_passes_a_valid_mapping():
    mcu_map = {"variant": "STM32F411",
               "pin_alternate_functions": {"PB6": ["I2C1_SCL"], "PB7": ["I2C1_SDA"]}}
    rep = _run([_bme280(), _ssd1306()], mcu_map)
    assert rep.checks["resource_crosscheck"] == "pass"
    # capability WAS verified here, so the "not verified" note must be absent
    assert not any("NOT verified" in n for n in rep.notes)


def test_pin_absent_from_the_af_table_is_not_treated_as_impossible():
    """The table's silence about a pin is not evidence the pin is wrong — we do
    not know the table is complete, so we do not fail on it."""
    mcu_map = {"pin_alternate_functions": {"PB6": ["I2C1_SCL"]}}
    rep = _run([_bme280(), _ssd1306()], mcu_map)   # PB7 is not in the table
    assert rep.checks["resource_crosscheck"] == "pass"


# --- the resource map (the V2 hero screen's data) ----------------------------

def test_build_resource_map_groups_claimants_by_resource():
    rmap = build_resource_map([_bme280(), _ssd1306(), _relay("PB6")])
    assert rmap["device_count"] == 3
    assert {c["device"] for c in rmap["pins"]["PB6"]} == {"BME280", "SSD1306", "Relay"}
    assert sorted(rmap["buses"]) == ["I2C1"]
    assert {b["device"] for b in rmap["buses"]["I2C1"]} == {"BME280", "SSD1306"}


def test_build_resource_map_accepts_shorthand_claims():
    rmap = build_resource_map([{"name": "A", "pins": ["PB6"], "irq": ["EXTI0"]},
                               {"name": "B", "pins": ["PB6"]}])
    assert len(rmap["pins"]["PB6"]) == 2
    assert "EXTI0" in rmap["irq"]


def test_shorthand_pin_claims_still_conflict():
    rep = _run([{"name": "A", "pins": ["PB6"]}, {"name": "B", "pins": ["PB6"]}])
    assert rep.checks["resource_crosscheck"] == "fail"
    assert "PB6" in _messages(rep)
