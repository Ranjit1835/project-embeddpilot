"""V2 workstream 3: the resource cross-check WIRED INTO the validator CLI.

test_v2_resource_crosscheck.py proves the check itself. This file proves the
integration, which is where a system-level check usually dies quietly:

  * a composed run with a conflict must reach report.failures and the verdict
    must be `failed` — never `validated`;
  * a run WITHOUT --devices must report `not_applicable` — not a pass, not a
    skip, and not a silent absence — and must leave every V1 behaviour alone;
  * the scope panel must render the three states distinctly.

The compile / static checks are stubbed here: they need a cross-toolchain this
box may not have, and they are not what is under test. Stubbing them to the
state a healthy box produces is what lets the assertions be about the VERDICT
(`validated` vs `failed`) rather than about a missing compiler.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import validator.__main__ as cli
from validator.report import Failure, ValidationReport
from validator.resource_crosscheck import resource_crosscheck
from validator.scope import build_scope

# --- a minimal single-device V1 run that validates cleanly -------------------

REGISTER_MAP = {
    "peripheral": "BME280",
    "provenance": {"peripheral": "detected"},
    "registers": [
        {"name": "ID", "offset": "0xD0"},
        {"name": "CTRL_MEAS", "offset": "0xF4"},
    ],
}

DRIVER_H = """#ifndef BME280_DRIVER_H
#define BME280_DRIVER_H
#include <stdint.h>
#define BME280_I2C_ADDR              0x76
#define BME280_ID_OFFSET             0xD0
#define BME280_CTRL_MEAS_OFFSET      0xF4
int bme280_read_id(uint8_t *out);
#endif
"""

DRIVER_C = """#include "bme280_driver.h"
int bme280_read_id(uint8_t *out) { *out = 0; return 0; }
"""


def _bme280(address="0x76"):
    return {"name": "BME280",
            "pins": [{"pin": "PB6", "function": "I2C1_SCL"},
                     {"pin": "PB7", "function": "I2C1_SDA"}],
            "bus": {"kind": "i2c", "instance": "I2C1", "address": address,
                    "speed_hz": 400000}}


def _ssd1306(address="0x3C"):
    return {"name": "SSD1306",
            "pins": [{"pin": "PB6", "function": "I2C1_SCL"},
                     {"pin": "PB7", "function": "I2C1_SDA"}],
            "bus": {"kind": "i2c", "instance": "I2C1", "address": address,
                    "speed_hz": 400000}}


@pytest.fixture
def run_cli(tmp_path, monkeypatch):
    """Drive `python -m validator` in-process; returns (exit_code, report)."""
    workdir = tmp_path / "out"
    workdir.mkdir()
    (workdir / "bme280_driver.h").write_text(DRIVER_H, encoding="utf-8")
    (workdir / "bme280_driver.c").write_text(DRIVER_C, encoding="utf-8")
    map_path = tmp_path / "register-map.json"
    map_path.write_text(json.dumps(REGISTER_MAP), encoding="utf-8")

    monkeypatch.setattr(cli, "compile_check",
                        lambda wd, plat, rep: rep.checks.__setitem__("compile", "pass"))
    monkeypatch.setattr(cli, "static_check",
                        lambda wd, rep: rep.checks.__setitem__("static_analysis", "pass"))

    def _run(devices=None, devices_payload_raw=None):
        argv = ["validator", str(workdir), "--map", str(map_path)]
        if devices is not None or devices_payload_raw is not None:
            dev_path = tmp_path / "devices.json"
            payload = devices if devices_payload_raw is None else devices_payload_raw
            dev_path.write_text(json.dumps(payload), encoding="utf-8")
            argv += ["--devices", str(dev_path)]
        out_path = tmp_path / "report.json"
        argv += ["--out", str(out_path)]
        monkeypatch.setattr(sys, "argv", argv)
        code = cli.main()
        return code, json.loads(out_path.read_text(encoding="utf-8"))

    return _run


def _resource_failures(report: dict) -> list[dict]:
    return [f for f in report["failures"] if f["check"] == "resource_crosscheck"]


def _item(report: dict, number: int) -> dict:
    return next(s for s in report["scope"] if s["item"] == number)


# --- 1. the composed run: a conflict is a hard failure -----------------------

def test_cli_conflict_is_a_failure_and_run_is_not_validated(run_cli):
    """Two devices strapped to the same 7-bit address on one bus. Each driver is
    individually fine; the SYSTEM cannot work."""
    code, report = run_cli(devices=[_bme280("0x76"), _ssd1306("0x76")])
    assert report["checks"]["resource_crosscheck"] == "fail"
    conflicts = _resource_failures(report)
    assert conflicts, "the conflict must be recorded as a Failure, not a note"
    assert "0x76" in conflicts[0]["message"]
    # the whole point: a composed run with a conflict never reaches validated
    assert report["status"] == "failed"
    assert code == cli.EXIT_CODES["failed"] == 2


def test_cli_pin_double_booking_is_a_failure(run_cli):
    relay = {"name": "Relay", "pins": [{"pin": "PB6", "function": "GPIO_OUT"}]}
    code, report = run_cli(devices=[_bme280(), _ssd1306(), relay])
    assert report["checks"]["resource_crosscheck"] == "fail"
    assert any("PB6" in f["message"] for f in _resource_failures(report))
    assert report["status"] == "failed"
    assert code == 2


def test_cli_clean_composition_passes_and_still_validates(run_cli):
    """The check must not cry wolf: a legitimate two-device I2C bus validates."""
    code, report = run_cli(devices=[_bme280("0x76"), _ssd1306("0x3C")])
    assert report["checks"]["resource_crosscheck"] == "pass"
    assert not _resource_failures(report)
    assert report["status"] == "validated"
    assert code == 0


# --- 2. the single-device run: not_applicable, and V1 untouched --------------

def test_cli_without_devices_is_not_applicable(run_cli):
    code, report = run_cli()
    assert report["checks"]["resource_crosscheck"] == "not_applicable"
    assert not _resource_failures(report)
    assert report["status"] == "validated"
    assert code == 0


def test_not_applicable_is_present_not_silently_skipped(run_cli):
    """`not_applicable` must be REPORTED. An absent key would read as 'this was
    checked and was fine' to anyone scanning the report."""
    _code, report = run_cli()
    assert "resource_crosscheck" in report["checks"]
    assert report["checks"]["resource_crosscheck"] != "skipped"
    assert any("not applicable" in n for n in report["notes"])


def test_single_device_list_is_also_not_applicable(run_cli):
    """One device supplied explicitly is still nothing to COMPOSE."""
    _code, report = run_cli(devices=[_bme280()])
    assert report["checks"]["resource_crosscheck"] == "not_applicable"
    assert report["status"] == "validated"


def test_existing_v1_behaviour_is_byte_identical_apart_from_the_new_check(run_cli):
    """Regression guard: adding the check must change NOTHING about a V1 run
    except the new check entry and its own note."""
    _c1, without = run_cli()
    _c2, with_clean = run_cli(devices=[_bme280("0x76"), _ssd1306("0x3C")])

    for report in (without, with_clean):
        assert report["checks"]["register_crosscheck"] == "pass"
        assert report["checks"]["math_crosscheck"] == "not_applicable"
        assert report["checks"]["compile"] == "pass"
        assert report["failures"] == []
        assert report["unverified_fields"] == []

    stripped = {k: v for k, v in without["checks"].items()
                if k != "resource_crosscheck"}
    assert stripped == {"register_crosscheck": "pass",
                        "math_crosscheck": "not_applicable",
                        "compile": "pass", "static_analysis": "pass"}
    assert without["status"] == with_clean["status"] == "validated"


def test_malformed_devices_file_stops_the_run(run_cli):
    """--devices was explicitly asked for; garbage must not degrade to a quiet
    not_applicable."""
    with pytest.raises(SystemExit) as exc:
        run_cli(devices_payload_raw={"nope": 1})
    assert exc.value.code == 2   # argparse usage error == the 'failed' exit code


# --- 3. finalize(): a resource conflict can never reach 'validated' ----------

def _otherwise_perfect() -> ValidationReport:
    rep = ValidationReport()
    rep.checks["register_crosscheck"] = "pass"
    rep.checks["compile"] = "pass"
    rep.checks["static_analysis"] = "pass"
    return rep


def test_finalize_treats_a_resource_conflict_as_a_hard_failure():
    rep = _otherwise_perfect()
    resource_crosscheck([_bme280("0x76"), _ssd1306("0x76")], None, rep)
    assert rep.checks["resource_crosscheck"] == "fail"
    assert rep.finalize().status == "failed"


def test_finalize_does_not_downgrade_a_clean_composition():
    rep = _otherwise_perfect()
    resource_crosscheck([_bme280("0x76"), _ssd1306("0x3C")], None, rep)
    assert rep.checks["resource_crosscheck"] == "pass"
    assert rep.finalize().status == "validated"


def test_finalize_not_applicable_is_not_a_failure():
    rep = _otherwise_perfect()
    resource_crosscheck(None, None, rep)
    assert rep.checks["resource_crosscheck"] == "not_applicable"
    assert rep.finalize().status == "validated"


# --- 4. the scope panel renders the three states distinctly -----------------

def _scope_pin_detail(rep: ValidationReport) -> str:
    return next(s for s in build_scope("bare-metal", REGISTER_MAP, rep, False)
                if s["item"] == 5)["detail"]


def test_scope_surfaces_resource_pass():
    rep = _otherwise_perfect()
    resource_crosscheck([_bme280("0x76"), _ssd1306("0x3C")], None, rep)
    detail = _scope_pin_detail(rep)
    assert "no conflict exists" in detail
    assert "NOT checked" not in detail


def test_scope_surfaces_resource_fail():
    rep = _otherwise_perfect()
    resource_crosscheck([_bme280("0x76"), _ssd1306("0x76")], None, rep)
    detail = _scope_pin_detail(rep)
    assert "hard failure" in detail
    assert "resource conflict" in detail


def test_scope_surfaces_not_applicable_without_claiming_a_pass():
    rep = _otherwise_perfect()
    resource_crosscheck(None, None, rep)
    detail = _scope_pin_detail(rep)
    assert "NOT checked" in detail
    assert "no conflict exists" not in detail


def test_scope_states_are_three_distinct_texts():
    details = []
    for devices in (None,
                    [_bme280("0x76"), _ssd1306("0x3C")],
                    [_bme280("0x76"), _ssd1306("0x76")]):
        rep = _otherwise_perfect()
        resource_crosscheck(devices, None, rep)
        details.append(_scope_pin_detail(rep))
    assert len(set(details)) == 3


def test_scope_status_vocabulary_is_unchanged():
    """No new status words were invented for this check."""
    allowed = {"cross-checked", "marked-unverified", "platform-owned",
               "your-input", "not-covered"}
    rep = _otherwise_perfect()
    resource_crosscheck([_bme280("0x76"), _ssd1306("0x76")], None, rep)
    for item in build_scope("bare-metal", REGISTER_MAP, rep, False):
        assert item["status"] in allowed


def test_scope_resource_note_does_not_move_any_item_status():
    """The note is cross-cutting honesty text; it must not silently re-badge the
    pin item (which the target/MCU-map logic owns)."""
    clean = _otherwise_perfect()
    resource_crosscheck(None, None, clean)
    conflicted = _otherwise_perfect()
    resource_crosscheck([_bme280("0x76"), _ssd1306("0x76")], None, conflicted)
    a = {s["item"]: s["status"] for s in build_scope("arduino", REGISTER_MAP, clean, False)}
    b = {s["item"]: s["status"] for s in build_scope("arduino", REGISTER_MAP, conflicted, False)}
    assert a == b
    assert a[5] == "platform-owned"


# --- 5. the failure record itself -------------------------------------------

def test_conflicts_are_attributed_to_the_resource_check(run_cli):
    _code, report = run_cli(devices=[_bme280("0x76"), _ssd1306("0x76")])
    assert all(f["check"] == "resource_crosscheck" for f in report["failures"])
    assert isinstance(Failure("resource_crosscheck", "", None, "x").message, str)
