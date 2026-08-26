"""V2 end-to-end: requirement text in, emulated verdict out.

This is the V2_PLAN §10 spike as an executable test. The individual pieces have
their own suites; what is asserted here is that the CHAIN holds — and, crucially,
that it refuses at every point it is supposed to refuse.
"""

from __future__ import annotations

import os

import pytest

from generation.provider import MockProvider
from orchestration.v2_pipeline import (
    FIXTURE_DIR,
    find_arm_gcc,
    run_application_pipeline,
)
from validator.emulation_check import find_renode

needs_tools = pytest.mark.skipif(
    find_renode() is None or find_arm_gcc() is None,
    reason="needs Renode + arm-none-eabi-gcc")

REQ = ("Read the BMP180 over I2C at address 0x77 and print the raw temperature "
       "over UART.")

# Answers a human would give to the questions the intake raises. Everything the
# model is allowed to contribute must be GROUNDED in REQ (quoted verbatim), so
# this extraction is legal; anything ungrounded would be dropped and re-asked.
ANSWERS = {
    "q:target.board": "Nucleo-F411RE",
    "q:target.mcu": "STM32F411RET6",
    "q:behaviors": "read temperature and print it over UART",
    "q:failure_behavior": "retry",
    "q:output_target": "cmake-project",
    "q:behaviors[0].trigger.source": "temperature",
    "q:behaviors[0].trigger.comparator": ">",
    "q:behaviors[0].trigger.threshold": "30 C",
    "q:constraints.sample_rate": "500 ms",
}

EXPECT = ["EP-EMU-BOOT", "BMP180-UT=18225", "EP-EMU-DONE"]


def _provider():
    """Grounded extraction only — every value is quoted from REQ."""
    return MockProvider([{"devices": [{
        "name": {"value": "BMP180", "evidence": "BMP180"},
        "interface": {"value": "I2C", "evidence": "over I2C"},
        "address": {"value": "0x77", "evidence": "address 0x77"},
        "role": {"value": "temperature", "evidence": "raw temperature"},
    }]}] + [{} for _ in range(9)])


def _run(**kw):
    return run_application_pipeline(
        REQ, answers=dict(ANSWERS), provider=_provider(),
        firmware_source=os.path.join(FIXTURE_DIR, "bmp180_temp.c"),
        expect=EXPECT, **kw)


# --- the pipeline must refuse before it builds ------------------------------

def test_vague_requirement_blocks_and_generates_nothing():
    """no spec line => no code. A vague requirement must stop at intake."""
    r = run_application_pipeline("monitor temperature and turn on a fan",
                                 provider=MockProvider([{}]))
    assert r["status"] == "needs-clarification"
    assert r["questions"], "must say what it needs, not guess"
    assert r["firmware_origin"] is None, "nothing may be generated"
    assert [s["stage"] for s in r["stages"]] == ["spec"]


# --- the chain ---------------------------------------------------------------

@needs_tools
def test_requirement_to_emulated_working():
    """The spike: a requirement becomes firmware that provably runs."""
    r = _run(stimulus={"Temperature": 24})
    stages = {s["stage"]: s["state"] for s in r["stages"]}
    assert stages["spec"] == "pass"
    assert stages["compose"] == "pass"
    assert stages["compile"] == "pass"
    assert stages["emulate"] == "pass"
    assert r["status"] == "working-emulated"
    # the verdict must label its own scope — emulation is not hardware
    assert "NOT evidence it works on physical hardware" in r["verdict_note"]


@needs_tools
def test_verdict_depends_on_the_mocked_value():
    """Load-bearing at PIPELINE level: same requirement, same firmware, same
    expectation, different mocked temperature -> the application is no longer
    working. If this ever returns working-emulated the whole verdict is hollow."""
    r = _run(stimulus={"Temperature": 60})
    assert r["status"] == "not-working"


@needs_tools
def test_fixture_firmware_is_never_labelled_generated():
    """Presenting a hand-written fixture as generated output would be a lie
    about what the system can do."""
    r = _run(stimulus={"Temperature": 24})
    assert r["firmware_origin"] == "fixture"


# --- the static moat blocks before anything is emulated ---------------------

def test_pin_conflict_blocks_before_emulation():
    """A system that cannot physically work must never reach the emulator and
    must never be called working."""
    from validator.report import ValidationReport
    from validator.resource_crosscheck import resource_crosscheck

    devices = [
        {"name": "BME280",
         "pins": [{"pin": "PB6", "function": "I2C1_SCL"}],
         "bus": {"kind": "i2c", "instance": "I2C1", "address": "0x76"}},
        {"name": "Relay", "pins": [{"pin": "PB6", "function": "GPIO_OUT"}]},
    ]
    rep = ValidationReport()
    resource_crosscheck(devices, None, rep)
    assert rep.checks["resource_crosscheck"] == "fail"
    assert any("PB6" in f.message for f in rep.failures)
