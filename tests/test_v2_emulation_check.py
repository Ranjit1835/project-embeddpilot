"""V2 WS5: the emulation check — does the firmware actually run?

The tests that need the real toolchain are marked and skip cleanly, exactly the
way the check itself degrades in production (the `needs_cc` precedent in
`test_v110_math_crosscheck.py`). The tests that encode the HONESTY rules —
skipped-never-passes, no-substitute-sensors, a hang is a failure — are the point
of the file, so the ones that can run without Renode do run everywhere.

The firmware under test is hand-written bare-metal STM32F4 in
`tests/fixtures/emulation/`. It is deliberately NOT generated: this file must be
able to fail when the emulation harness is broken, which it cannot do if the
thing it runs is produced by the same pipeline it is meant to police.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess

import pytest

from validator.emulation_check import (
    _resolve_model,
    emulation_check,
    find_renode,
    model_catalogue,
    renode_root,
)
from validator.report import ValidationReport

CHECK = "emulation_check"
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "emulation")

RENODE = find_renode()
needs_renode = pytest.mark.skipif(RENODE is None, reason="Renode not available")


def find_arm_gcc() -> str | None:
    """arm-none-eabi-gcc from PATH or the PlatformIO toolchain package."""
    found = shutil.which("arm-none-eabi-gcc")
    if found:
        return found
    home = os.path.expanduser("~")
    for pattern in (
        os.path.join(home, ".platformio", "packages", "toolchain-gccarmnoneeabi*",
                     "bin", "arm-none-eabi-gcc*"),
    ):
        matches = [p for p in sorted(glob.glob(pattern))
                   if os.path.basename(p) in ("arm-none-eabi-gcc",
                                              "arm-none-eabi-gcc.exe")]
        if matches:
            return matches[0]
    return None


ARM_GCC = find_arm_gcc()
needs_arm_gcc = pytest.mark.skipif(ARM_GCC is None, reason="no arm-none-eabi-gcc")


def build_fixture(dest_dir: str, source: str = "bmp180_probe.c") -> str:
    """Compile the hand-written fixture firmware to an ELF in `dest_dir`."""
    elf = os.path.join(dest_dir, "firmware.elf")
    proc = subprocess.run(
        [ARM_GCC, "-mcpu=cortex-m4", "-mthumb", "-Os", "-ffreestanding",
         "-nostdlib", "-nostartfiles", "-Wall", "-Wextra",
         "-T", os.path.join(FIXTURES, "stm32f4.ld"),
         os.path.join(FIXTURES, source), "-o", elf],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, f"fixture build failed: {proc.stderr}"
    return elf


def bmp180_spec(**overrides) -> dict:
    """The V2 shape: one composed device, mocked by ITS OWN Renode model, with
    the firmware's observable UART behaviour asserted."""
    spec = {
        "target": {"platform": "platforms/cpus/stm32f4.repl", "uart": "usart2",
                   "firmware": "firmware.elf", "run_for": "0.5", "timeout": 120},
        "devices": [{
            "name": "BMP180",
            "bus": {"kind": "i2c", "instance": "I2C1", "address": "0x77"},
            "stimulus": {"Temperature": 24},
        }],
        # 0x55 is the BMP180 chip-ID the datasheet specifies at register 0xD0.
        "expect": ["EP-EMU-BOOT", "BMP180-ID=0x55", "EP-EMU-DONE"],
        "reject": ["BMP180-READ-FAILED"],
    }
    spec.update(overrides)
    return spec


# --- applicability: nothing to emulate is NOT a pass and NOT a skip ---------

def test_no_devices_is_not_applicable(tmp_path):
    rep = ValidationReport()
    emulation_check(str(tmp_path), {"expect": ["hi"]}, rep)
    assert rep.checks[CHECK] == "not_applicable"
    assert not rep.failures


def test_no_expectations_is_not_applicable(tmp_path):
    """Running firmware while asserting nothing demonstrates nothing."""
    rep = ValidationReport()
    emulation_check(str(tmp_path), {"devices": [{"name": "BMP180"}]}, rep)
    assert rep.checks[CHECK] == "not_applicable"
    assert not rep.failures


def test_empty_spec_is_not_applicable(tmp_path):
    rep = ValidationReport()
    emulation_check(str(tmp_path), None, rep)
    assert rep.checks[CHECK] == "not_applicable"


# --- the harness could not run: skipped, and NEVER pass ---------------------

def test_renode_missing_is_skipped_never_pass(tmp_path, monkeypatch):
    """The central rule: a check that could not run promotes no one."""
    monkeypatch.setattr("validator.emulation_check.find_renode", lambda: None)
    rep = ValidationReport()
    emulation_check(str(tmp_path), bmp180_spec(), rep)
    assert rep.checks[CHECK] == "skipped"
    assert rep.checks[CHECK] != "pass"
    assert not rep.failures
    assert any("NOT executed" in n for n in rep.notes)


@needs_renode
def test_missing_firmware_is_skipped(tmp_path):
    """Nothing built means nothing to run — a gap in coverage, not a defect."""
    rep = ValidationReport()
    emulation_check(str(tmp_path), bmp180_spec(), rep)
    assert rep.checks[CHECK] == "skipped"
    assert any("no firmware ELF" in n for n in rep.notes)


@needs_renode
def test_unknown_platform_is_skipped(tmp_path):
    spec = bmp180_spec()
    spec["target"]["platform"] = "platforms/cpus/definitely-not-a-board.repl"
    rep = ValidationReport()
    emulation_check(str(tmp_path), spec, rep)
    assert rep.checks[CHECK] == "skipped"


# --- the mocked-sensor rule: never substitute a different part --------------

@needs_renode
def test_device_without_a_renode_model_is_skipped_not_substituted(tmp_path):
    """BME280 has no model in this Renode build. A BMP180 standing in for it
    would turn the run green while proving nothing about the BME280 code."""
    spec = bmp180_spec(devices=[{
        "name": "BME280",
        "bus": {"kind": "i2c", "instance": "I2C1", "address": "0x76"},
    }])
    rep = ValidationReport()
    emulation_check(str(tmp_path), spec, rep)
    assert rep.checks[CHECK] == "skipped"
    assert rep.checks[CHECK] != "pass"
    note = " ".join(rep.notes)
    assert "BME280" in note and "UNVERIFIED" in note


def test_resolve_model_never_approximates():
    """Unit-level guard on the resolution rule itself: a near-miss name must
    resolve to nothing, not to the nearest available sensor."""
    catalogue = {"BMP180": "Sensors.BMP180", "SI70XX": "Sensors.SI70xx"}
    assert _resolve_model({"name": "BMP180"}, catalogue) == "Sensors.BMP180"
    assert _resolve_model({"name": "BME280"}, catalogue) is None
    assert _resolve_model({"name": "BMP185"}, catalogue) is None
    # an explicit caller declaration is always honoured
    assert _resolve_model(
        {"name": "BME280", "renode_model": "Sensors.BME280"}, catalogue
    ) == "Sensors.BME280"


@needs_renode
def test_catalogue_is_scanned_from_the_installation():
    catalogue = model_catalogue(renode_root(RENODE))
    assert catalogue.get("BMP180") == "Sensors.BMP180"
    # absence is real, and is what the skip above is grounded in
    assert "BME280" not in catalogue


@needs_renode
def test_device_without_bus_address_is_skipped(tmp_path):
    spec = bmp180_spec(devices=[{"name": "BMP180", "bus": {"instance": "I2C1"}}])
    rep = ValidationReport()
    emulation_check(str(tmp_path), spec, rep)
    assert rep.checks[CHECK] == "skipped"


# --- a hung emulation FAILS, it never hangs the validator --------------------

@needs_renode
@needs_arm_gcc
def test_timeout_is_a_failure(tmp_path):
    """A wall-clock ceiling below Renode's own startup time forces the kill
    path. `emulation RunFor` bounds VIRTUAL time only — real time needs this."""
    build_fixture(str(tmp_path))
    spec = bmp180_spec()
    spec["target"]["timeout"] = 1
    rep = ValidationReport()
    emulation_check(str(tmp_path), spec, rep)
    assert rep.checks[CHECK] == "fail"
    assert any("did not finish" in f.message for f in rep.failures)


# --- the real thing: firmware, mocked device, asserted behaviour ------------

@needs_renode
@needs_arm_gcc
def test_firmware_reads_mocked_sensor_and_passes(tmp_path):
    """The V2 gate in one test: hand-written firmware boots on an emulated
    STM32F4, reads the chip ID out of a mocked BMP180 over emulated I2C1, and
    reports it on emulated USART2 where the spec's patterns are asserted."""
    build_fixture(str(tmp_path))
    rep = ValidationReport()
    emulation_check(str(tmp_path), bmp180_spec(), rep)
    assert rep.checks[CHECK] == "pass", [f.message for f in rep.failures]
    assert not rep.failures
    note = " ".join(rep.notes)
    assert "Sensors.BMP180" in note
    # the verdict must label its own scope
    assert "not evidence that the firmware works on physical hardware" in note


@needs_renode
@needs_arm_gcc
def test_wrong_expectation_fails(tmp_path):
    """The harness must be able to FAIL. A pass that cannot fail is decoration."""
    build_fixture(str(tmp_path))
    spec = bmp180_spec(expect=["BMP180-ID=0x99"])
    rep = ValidationReport()
    emulation_check(str(tmp_path), spec, rep)
    assert rep.checks[CHECK] == "fail"
    assert any("never produced the required output" in f.message
               for f in rep.failures)
    # the failure must carry what was ACTUALLY seen, or it cannot be debugged
    assert any("BMP180-ID=0x55" in f.message for f in rep.failures)


@needs_renode
@needs_arm_gcc
def test_forbidden_output_fails(tmp_path):
    build_fixture(str(tmp_path))
    spec = bmp180_spec(reject=["EP-EMU-BOOT"])
    rep = ValidationReport()
    emulation_check(str(tmp_path), spec, rep)
    assert rep.checks[CHECK] == "fail"
    assert any("forbidden output" in f.message for f in rep.failures)


@needs_renode
@needs_arm_gcc
def test_silent_uart_fails(tmp_path):
    """Asserting on a UART the firmware never writes must fail, not pass by
    vacuous absence of contradiction."""
    build_fixture(str(tmp_path))
    spec = bmp180_spec()
    spec["target"]["uart"] = "uart5"
    rep = ValidationReport()
    emulation_check(str(tmp_path), spec, rep)
    assert rep.checks[CHECK] == "fail"
    assert any("NO output at all" in f.message for f in rep.failures)


@needs_renode
@needs_arm_gcc
def test_regex_expectation(tmp_path):
    build_fixture(str(tmp_path))
    spec = bmp180_spec(expect=[
        {"pattern": r"BMP180-ID=0x[0-9A-F]{2}", "kind": "regex",
         "description": "chip id reported"}])
    rep = ValidationReport()
    emulation_check(str(tmp_path), spec, rep)
    assert rep.checks[CHECK] == "pass", [f.message for f in rep.failures]


@needs_renode
@needs_arm_gcc
def test_bad_model_is_reported_as_renode_error_not_a_pass(tmp_path):
    """An explicitly-declared model that Renode cannot resolve must surface as a
    failure carrying Renode's own message — never a silent pass. Renode exits 0
    in this case, so nothing may depend on its exit code."""
    build_fixture(str(tmp_path))
    spec = bmp180_spec(devices=[{
        "name": "Imaginary",
        "renode_model": "Sensors.NotARealPart",
        "bus": {"instance": "I2C1", "address": "0x77"},
    }])
    rep = ValidationReport()
    emulation_check(str(tmp_path), spec, rep)
    assert rep.checks[CHECK] == "fail"
    assert any("Could not resolve type" in f.message for f in rep.failures)


# --- sandboxing --------------------------------------------------------------

@needs_renode
@needs_arm_gcc
def test_run_writes_nothing_into_the_renode_installation(tmp_path):
    """Renode resolves a bare `@path` against its OWN root, so a naive capture
    lands the UART log inside the installation. The check must not do that."""
    root = renode_root(RENODE)
    before = set(os.listdir(root))
    build_fixture(str(tmp_path))
    rep = ValidationReport()
    emulation_check(str(tmp_path), bmp180_spec(), rep)
    assert rep.checks[CHECK] == "pass"
    assert set(os.listdir(root)) == before


@needs_renode
def test_generated_platform_has_no_remote_svd_fetch(tmp_path):
    """The shipped stm32f4.repl fetches an SVD over HTTPS at load time. The
    derived platform must re-emit the init block without it so a run needs no
    network."""
    from validator.emulation_check import _build_repl

    notes: list[str] = []
    repl = _build_repl(renode_root(RENODE), "platforms/cpus/stm32f4.repl",
                       [("bmp180", "Sensors.BMP180", "i2c1", 0x77)], notes)
    assert "Sensors.BMP180 @ i2c1 0x77" in repl
    assert "@http" not in repl
    assert "ApplySVD" not in repl
    # the functional init directives must survive
    assert "USB:RESET" in repl


# --- the stimulus must be LOAD-BEARING -------------------------------------
#
# The original harness proved "firmware runs and talks to a mocked device". It
# did NOT prove that the mocked device's VALUE reaches the assertion: the probe
# firmware read only the chip ID, so its pass would have survived any
# Temperature. These two tests close that gap and are the reason the emulation
# verdict means anything — if they ever both pass with the SAME expected UT, the
# stimulus has stopped mattering and the check has quietly become decoration.
#
# UT is the BMP180's UNCOMPENSATED temperature word. We assert the raw value on
# purpose: BMP180's compensation algorithm lives in a datasheet FIGURE and is not
# extractable (V1.10a), so there is no math oracle for it and computing a
# temperature here would be inventing the algorithm from memory.
#
# 18225 is not a formula — it is the value Renode's BMP180 model was OBSERVED to
# emit for Temperature=24 on this build.

UT_AT_24 = "BMP180-UT=18225"


def _temp_spec(temperature, expect):
    spec = bmp180_spec(expect=expect)
    spec["target"]["firmware"] = "firmware.elf"
    spec["devices"][0]["stimulus"] = {"Temperature": temperature}
    return spec


@needs_renode
@needs_arm_gcc
def test_mocked_value_reaches_the_assertion(tmp_path):
    """Temperature=24 -> the firmware's raw read reports the UT that stimulus
    produces, and the spec asserting it passes."""
    build_fixture(str(tmp_path), source="bmp180_temp.c")
    rep = ValidationReport()
    emulation_check(str(tmp_path),
                    _temp_spec(24, ["EP-EMU-BOOT", UT_AT_24, "EP-EMU-DONE"]),
                    rep)
    assert rep.checks[CHECK] == "pass", [f.message for f in rep.failures]


@needs_renode
@needs_arm_gcc
def test_changing_the_stimulus_changes_the_verdict(tmp_path):
    """The proof. Same firmware, same expectation, DIFFERENT stimulus -> the
    check must FAIL. If this ever passes, the mocked value is not reaching the
    assertion and every emulation 'pass' is worth less than it appears."""
    build_fixture(str(tmp_path), source="bmp180_temp.c")
    rep = ValidationReport()
    emulation_check(str(tmp_path),
                    _temp_spec(60, ["EP-EMU-BOOT", UT_AT_24, "EP-EMU-DONE"]),
                    rep)
    assert rep.checks[CHECK] == "fail"
    # and the failure must show what the different stimulus actually produced
    assert any("BMP180-UT=" in f.message for f in rep.failures)
