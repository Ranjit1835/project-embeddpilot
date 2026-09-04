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
    # the raw 16-bit device word is combined and reported as-is; asserted by
    # intent rather than by one exact line, so a refactor of HOW it is printed
    # cannot silently turn into a refactor of WHETHER it stays raw
    assert "((uint32_t)b0 << 8) | (uint32_t)b1" in code
    assert "float" not in code and "compensat" not in code.lower().replace(
        "no compensation", "")


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


# --- generality: the plan is DERIVED from the V1 register map ---------------
#
# Hand-writing a ReadPlan per chip would make the generator a BMP180 demo. These
# assert the real capability: any device V1 can ingest and cross-check becomes an
# application we can generate and prove. Every address in the derived plan comes
# from the map; none is remembered or defaulted.

import json  # noqa: E402

from generation.app_worker import derive_read_plan  # noqa: E402

MAP_PATH = os.path.join(os.path.dirname(__file__), "..", "artifacts",
                        "bmp180-extracted-map.json")


def _bmp180_map():
    if not os.path.exists(MAP_PATH):
        pytest.skip("bmp180-extracted-map.json not present")
    with open(MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_plan_is_derived_from_the_register_map():
    """The addresses must come from the map, not from the generator."""
    m = _bmp180_map()
    plan, notes = derive_read_plan(m, 0x77, measurement="Temperature")
    assert plan is not None, notes
    kinds = [s.kind for s in plan.steps]
    assert kinds == ["read8", "write8", "delay", "read16"]
    by_kind = {s.kind: s for s in plan.steps}
    assert by_kind["read8"].reg == 0xD0          # `id` in the map
    assert by_kind["write8"].reg == 0xF4         # `ctrl_meas` in the map
    assert by_kind["write8"].value == 0x2E       # the Temperature command opcode
    assert by_kind["read16"].reg == 0xF6         # `out_msb`
    assert by_kind["read16"].reg_lo == 0xF7      # `out_lsb`


def test_derivation_refuses_when_there_is_nothing_to_read():
    """A map with no identifiable data register yields no plan and a reason —
    never a plausible guess at an address the device may not have."""
    plan, notes = derive_read_plan(
        {"chip": "MYSTERY", "registers": [{"name": "cfg", "offset": "0x01"}]}, 0x40)
    assert plan is None
    assert any("nothing to read" in n or "refusing" in n for n in notes)


def test_missing_id_register_is_a_note_not_a_failure():
    """Absence of an ID register weakens the boot check; it does not stop us."""
    plan, notes = derive_read_plan({"chip": "X", "registers": [
        {"name": "out_msb", "offset": "0x10"},
        {"name": "out_lsb", "offset": "0x11"}]}, 0x40)
    assert plan is not None
    assert [s.kind for s in plan.steps] == ["read16"]
    assert any("no ID register" in n for n in notes)


@needs_tools
def test_map_derived_firmware_actually_runs():
    """End of the chain: ingested map -> derived plan -> generated firmware ->
    compiled -> booted on emulated silicon -> asserted. Nothing hand-written."""
    plan, _ = derive_read_plan(_bmp180_map(), 0x77, measurement="Temperature")
    r = run_application_pipeline(
        REQ, answers=dict(ANSWERS), provider=_provider(), read_plan=plan,
        expect=["EP-EMU-BOOT", "BMP180-ID=0x55", "BMP180-RAW=18225", "EP-EMU-DONE"],
        stimulus={"Temperature": 24})
    assert r["status"] == "working-emulated"
    assert r["firmware_origin"] == "generated"


# --- the application: trigger -> action, and a complete repo ----------------

from generation.app_worker import (  # noqa: E402
    AppGenerationError,
    Behavior,
    generate_project,
)

LD = os.path.join(os.path.dirname(__file__), "fixtures", "emulation", "stm32f4.ld")


def _plan_from_map():
    plan, _ = derive_read_plan(_bmp180_map(), 0x77, measurement="Temperature")
    return plan


def test_engineering_unit_threshold_is_refused_without_an_oracle():
    """THE integrity rule. A 'temp > 30 C' threshold needs raw -> C, which needs a
    verified math oracle. BMP180's conversion is figure-trapped (V1.10a), so the
    generator must refuse rather than invent the formula from memory."""
    with pytest.raises(AppGenerationError) as e:
        generate_application(_plan_from_map(),
                             Behavior(threshold=30, unit="C"),
                             has_math_oracle=False)
    assert "math oracle" in str(e.value)


def test_raw_threshold_is_allowed():
    """A threshold in raw device units needs no conversion, so nothing is
    invented and the behaviour is emittable."""
    code = generate_application(_plan_from_map(),
                                Behavior(threshold=18500, unit="raw",
                                         action_label="RELAY"))
    assert "RELAY=ON" in code and "RELAY=OFF" in code
    assert "for (uint32_t iter" in code, "an application samples in a bounded loop"


def test_generated_repo_is_complete_and_self_building():
    """The deliverable is a repo, not a loose .c file — and its README must state
    what was NOT verified as plainly as what was."""
    files = generate_project(_plan_from_map(),
                             Behavior(threshold=18500, unit="raw"),
                             linker_script=open(LD, encoding="utf-8").read())
    assert set(files) == {"src/main.c", "Makefile", "README.md", "link/stm32f4.ld"}
    readme = files["README.md"]
    assert "NOT performed" in readme      # raw -> engineering units
    assert "NOT verified" in readme       # physical hardware


@needs_tools
def test_behaviour_fires_only_when_the_reading_crosses_the_threshold():
    """The application actually works: the actuator follows the mocked sensor.
    18500 sits between the raw words for Temperature 24 (18225) and 60 (18972)."""
    import glob
    import subprocess
    import tempfile

    from validator.emulation_check import emulation_check
    from validator.report import ValidationReport

    code = generate_application(_plan_from_map(),
                                Behavior(threshold=18500, unit="raw",
                                         action_label="RELAY"))
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "app.c"), "w", encoding="utf-8", newline="\n") as f:
        f.write(code)
    gcc = glob.glob(os.path.expanduser(
        "~/.platformio/packages/toolchain-gccarmnoneeabi/bin/arm-none-eabi-gcc*"))[0]
    subprocess.run([gcc, "-mcpu=cortex-m4", "-mthumb", "-Os", "-ffreestanding",
                    "-nostdlib", "-nostartfiles", "-T", LD,
                    os.path.join(d, "app.c"), "-o", os.path.join(d, "firmware.elf")],
                   capture_output=True, check=True)

    def run(temp, expect):
        spec = {"target": {"platform": "platforms/cpus/stm32f4.repl",
                           "uart": "usart2", "firmware": "firmware.elf",
                           "run_for": "0.5", "timeout": 180},
                "devices": [{"name": "BMP180",
                             "bus": {"kind": "i2c", "instance": "I2C1",
                                     "address": "0x77"},
                             "stimulus": {"Temperature": temp}}],
                "expect": expect}
        rep = ValidationReport()
        emulation_check(d, spec, rep)
        return rep.checks["emulation_check"]

    assert run(24, ["RELAY=OFF"]) == "pass", "cold must not fire the actuator"
    assert run(60, ["RELAY=ON"]) == "pass", "hot must fire the actuator"
    # and the assertion must be capable of failing, or it proves nothing
    assert run(60, ["RELAY=OFF"]) == "fail"


# --- V2 runs V1's VERIFIED driver -------------------------------------------
#
# Until this section existed, V2 emitted its own I2C primitives and talked to the
# device directly — improvised device code sitting beside V1's verified driver
# rather than USING it. Two pipelines that never met. These assert the seam: V1
# owns device logic (cross-checked against the datasheet), V2 owns MCU bring-up,
# implements the driver's callbacks, and runs the application.

from generation.app_worker import (  # noqa: E402
    DriverInterface,
    generate_application_using_driver,
    parse_driver_interface,
)

V1_DRIVER_DIR = os.path.join(os.path.dirname(__file__), "..", "build",
                             "llm_gen", "lm75b", "attempt_1")


def _v1_driver():
    h = os.path.join(V1_DRIVER_DIR, "lm75b_driver.h")
    if not os.path.exists(h):
        pytest.skip("no V1-generated driver artifact present")
    with open(h, encoding="utf-8") as f:
        return f.read()


def test_driver_interface_is_read_from_the_header_not_guessed():
    iface, why = parse_driver_interface(_v1_driver(), "lm75b_driver.h")
    assert iface is not None, why
    assert iface.init_fn == "lm75b_init"
    assert iface.dev_type == "lm75b_dev_t"
    assert "raw" in iface.read_raw_fn, "must call the RAW reader, not a converted one"


def test_header_without_the_callback_shape_is_refused():
    """A driver that does not expose the callback seam cannot be driven, and we
    say which piece is missing rather than guessing a function name."""
    iface, why = parse_driver_interface("int something(void);", "x.h")
    assert iface is None
    assert any("callback typedef" in w for w in why)


def test_generated_app_delegates_the_device_to_the_driver():
    """The application must CALL the verified driver, and the only device-facing
    code it owns is the two bus callbacks."""
    iface, _ = parse_driver_interface(_v1_driver(), "lm75b_driver.h")
    code = generate_application_using_driver(iface, 0x48)
    assert '#include "lm75b_driver.h"' in code
    assert "lm75b_init(&dev" in code
    assert "lm75b_read_temp_raw(&dev" in code
    assert "lm75b_bus_read" in code and "lm75b_bus_write" in code
    # it must NOT re-derive the device's registers
    assert "0xD0" not in code and "TEMP_REG" not in code


def test_driver_path_still_refuses_unit_thresholds_without_an_oracle():
    iface, _ = parse_driver_interface(_v1_driver(), "lm75b_driver.h")
    with pytest.raises(AppGenerationError):
        generate_application_using_driver(
            iface, 0x48, Behavior(threshold=30, unit="C"), has_math_oracle=False)


@pytest.mark.skipif(find_arm_gcc() is None, reason="no arm-none-eabi-gcc")
def test_app_and_v1_driver_compile_and_link_together():
    """The proof: one firmware image containing the generated application AND
    the datasheet-verified driver, clean under -Wall -Wextra."""
    import shutil
    import subprocess
    import tempfile

    iface, _ = parse_driver_interface(_v1_driver(), "lm75b_driver.h")
    code = generate_application_using_driver(
        iface, 0x48, Behavior(threshold=100, unit="raw", action_label="FAN"))
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "app.c"), "w", encoding="utf-8", newline="\n") as f:
        f.write(code)
    for n in ("lm75b_driver.h", "lm75b_driver.c"):
        shutil.copy(os.path.join(V1_DRIVER_DIR, n), d)
    proc = subprocess.run(
        [find_arm_gcc(), "-mcpu=cortex-m4", "-mthumb", "-Os", "-ffreestanding",
         "-nostdlib", "-nostartfiles", "-Wall", "-Wextra", "-I", d,
         "-T", os.path.join(FIXTURE_DIR, "stm32f4.ld"),
         os.path.join(d, "app.c"), os.path.join(d, "lm75b_driver.c"),
         "-o", os.path.join(d, "fw.elf"),
         # V1 drivers may use float; -nostdlib drops libgcc's soft-float helpers
         "-lgcc"],
        capture_output=True, text=True, timeout=240)
    assert proc.returncode == 0, proc.stderr[:800]
    assert "warning:" not in proc.stderr, proc.stderr[:800]
    assert os.path.exists(os.path.join(d, "fw.elf"))


# --- multi-device: a real application is rarely one sensor ------------------
#
# The resource cross-check has always reasoned about a COMPOSED system; the
# generator emitted exactly one device, so a two-sensor application could be
# CHECKED but not BUILT. These assert the composed path — and the one honest
# decision it forces: WHICH device's reading drives the actuator.

from generation.app_worker import (  # noqa: E402
    expectations_for_system,
    generate_system,
)


def _two_devices():
    m = _bmp180_map()
    a, _ = derive_read_plan(m, 0x77, measurement="Temperature")
    b, _ = derive_read_plan(m, 0x76, measurement="Temperature")
    b.chip = "BMP180B"
    return a, b


def test_multi_device_refuses_to_guess_which_reading_drives_the_action():
    """With two readings available, which one triggers the relay is genuinely
    ambiguous. Choosing the first would be inventing a requirement."""
    a, b = _two_devices()
    with pytest.raises(AppGenerationError) as e:
        generate_system([a, b], Behavior(threshold=18500, unit="raw"))
    assert "does not say which one" in str(e.value)


def test_multi_device_refuses_an_address_collision():
    """Emitting firmware for a system that cannot physically work is worse than
    refusing to."""
    a, _ = _two_devices()
    dup, _ = derive_read_plan(_bmp180_map(), 0x77, measurement="Temperature")
    dup.chip = "DUP"
    with pytest.raises(AppGenerationError) as e:
        generate_system([a, dup])
    assert "same I2C address" in str(e.value)


def test_multi_device_labels_are_unique_per_device():
    """Two devices both reporting '<chip>-RAW=' would make a two-device system
    look like it worked while only one device was ever observed."""
    a, b = _two_devices()
    code = generate_system([a, b], Behavior(threshold=1, unit="raw"),
                           source_chip="BMP180")
    assert "BMP180-RAW=" in code and "BMP180B-RAW=" in code
    assert "0x77u" in code and "0x76u" in code
    exp = expectations_for_system([a, b], Behavior(threshold=1, unit="raw"))
    assert "BMP180-RAW=" in exp and "BMP180B-RAW=" in exp


@needs_tools
def test_two_device_system_runs_and_the_named_source_drives_the_action():
    """The composed application actually works: two devices on one I2C bus, and
    the actuator follows the device the spec NAMED — not whichever was read last."""
    import glob as _glob
    import subprocess
    import tempfile

    from validator.emulation_check import emulation_check
    from validator.report import ValidationReport

    a, b = _two_devices()
    code = generate_system([a, b],
                           Behavior(threshold=18500, unit="raw",
                                    action_label="RELAY"),
                           source_chip="BMP180")
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "app.c"), "w", encoding="utf-8", newline="\n") as f:
        f.write(code)
    subprocess.run(
        [find_arm_gcc(), "-mcpu=cortex-m4", "-mthumb", "-Os", "-ffreestanding",
         "-nostdlib", "-nostartfiles", "-T",
         os.path.join(FIXTURE_DIR, "stm32f4.ld"), os.path.join(d, "app.c"),
         "-o", os.path.join(d, "firmware.elf"), "-lgcc"],
        capture_output=True, check=True, timeout=240)

    def run(source_temp):
        spec = {
            "target": {"platform": "platforms/cpus/stm32f4.repl",
                       "uart": "usart2", "firmware": "firmware.elf",
                       "run_for": "0.5", "timeout": 240},
            "devices": [
                {"name": "BMP180",
                 "bus": {"kind": "i2c", "instance": "I2C1", "address": "0x77"},
                 "stimulus": {"Temperature": source_temp}},
                {"name": "BMP180B",
                 "bus": {"kind": "i2c", "instance": "I2C1", "address": "0x76"},
                 "renode_model": "Sensors.BMP180",
                 "stimulus": {"Temperature": 24}},
            ],
            "expect": ["EP-EMU-BOOT", "BMP180-RAW=", "BMP180B-RAW=",
                       "RELAY=ON", "EP-EMU-DONE"],
        }
        rep = ValidationReport()
        emulation_check(d, spec, rep)
        return rep.checks["emulation_check"]

    assert run(60) == "pass", "hot named source must fire the actuator"
    # the OTHER device stays at 24 in both runs, so a pass here would mean the
    # action was following the wrong device
    assert run(24) == "fail", "cold named source must not fire it"
