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


# --- WS4: the pipeline GENERATES the firmware it claims to produce ----------
#
# Until this section existed the pipeline proved the CHAIN worked while a
# hand-written fixture stood in for the artifact — a demo, not a product. These
# assert the real capability: firmware generated from the spec + the device's
# register facts, compiled, and proven to run.

from generation.app_worker import ReadPlan, Step, generate_application  # noqa: E402


def _bmp180_plan():
    """Device facts come from the BMP180 register map — the generator invents
    no register address, and the plan is the single source both the firmware and
    its expectations derive from."""
    return ReadPlan(chip="BMP180", address=0x77, steps=[
        Step("read8", label="BMP180-ID", reg=0xD0, expect_hex="55"),
        Step("write8", label="BMP180-START", reg=0xF4, value=0x2E),
        Step("delay", label="BMP180-WAIT", ticks=200000),
        Step("read16", label="BMP180-UT", reg=0xF6, reg_lo=0xF7),
    ])


def test_generation_is_deterministic():
    """Same spec in, byte-identical firmware out. Determinism is a V1 rule and
    it does not get relaxed because the output got bigger."""
    assert generate_application(_bmp180_plan()) == generate_application(_bmp180_plan())


def test_generator_refuses_to_invent_register_access():
    """No plan means no device facts. Emitting register accesses nobody
    specified is the exact failure this project exists to prevent."""
    from generation.app_worker import AppGenerationError
    with pytest.raises(AppGenerationError):
        generate_application(ReadPlan(chip="BMP180", address=0x77, steps=[]))


def test_generated_firmware_emits_no_compensation_math():
    """Converting a raw reading to engineering units needs a datasheet-grounded
    oracle; BMP180's lives in a figure (V1.10a). The firmware must report RAW."""
    code = generate_application(_bmp180_plan())
    assert "NOT converted to engineering units" in code
    assert "uart_u32(((uint32_t)b0 << 8) | (uint32_t)b1);" in code


@needs_tools
def test_pipeline_generates_firmware_that_actually_runs():
    """The product claim: a requirement becomes GENERATED firmware that boots on
    an emulated MCU, talks to a mocked device, and matches its expectations."""
    r = run_application_pipeline(
        REQ, answers=dict(ANSWERS), provider=_provider(), read_plan=_bmp180_plan(),
        expect=["EP-EMU-BOOT", "BMP180-ID=0x55", "BMP180-UT=18225", "EP-EMU-DONE"],
        stimulus={"Temperature": 24})
    stages = {s["stage"]: s["state"] for s in r["stages"]}
    assert stages["generate"] == "pass"
    assert stages["compile"] == "pass"
    assert stages["emulate"] == "pass"
    assert r["status"] == "working-emulated"
    assert r["firmware_origin"] == "generated", "generated code must not be mislabelled"


@needs_tools
def test_generated_firmware_verdict_is_load_bearing():
    """Generated code earns the same scrutiny as the fixture: change the mocked
    value and the verdict must change, or the pass means nothing."""
    r = run_application_pipeline(
        REQ, answers=dict(ANSWERS), provider=_provider(), read_plan=_bmp180_plan(),
        expect=["EP-EMU-BOOT", "BMP180-ID=0x55", "BMP180-UT=18225", "EP-EMU-DONE"],
        stimulus={"Temperature": 60})
    assert r["status"] == "not-working"
