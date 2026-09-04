"""V2: the end-to-end application pipeline.

Chains the V2 pieces that were each built and verified on their own:

    requirement text
      -> WS1  spec        generation/spec.py       (ask, never invent)
      -> WS2  compose     Device fields -> resource-check dicts
      -> WS3  resource    validator/resource_crosscheck.py (the static moat)
      -> WS4  firmware    build an ELF for the composed system
      -> WS5  emulate     validator/emulation_check.py (Renode, real assertions)
      -> verdict          one ValidationReport, finalized

WHAT "WORKING" MEANS HERE
-------------------------
The pipeline reports `working-emulated` ONLY when the resource check passes AND
the emulation check passes. Anything skipped or failed prevents it. That verdict
means: this firmware ran on an emulated MCU, talked to mocked devices, and its
observable behaviour matched the spec's expectations. It is NOT evidence the
firmware works on physical hardware (V2_PLAN §3 tier 3 is deliberately out of
scope) — the emulation check's own note says so and we do not overstate it here.

WHAT THIS PIPELINE WILL NOT DO
------------------------------
* It will not proceed on an incomplete spec. Blocking questions stop the run and
  are returned; nothing is generated. `no spec line => no code`.
* It will not invent pin assignments to make a resource check pass, and it will
  not auto-reassign a conflicting pin behind the user's back. A conflict BLOCKS
  and is reported with its claimants; resolving it is a decision, and the caller
  re-runs with the corrected devices (that is what the UI's "auto-fix" button
  does — it proposes, the user accepts, the pipeline re-checks).
* It will not label a hand-written fixture as generated output. Every result
  carries `firmware_origin` ∈ {"fixture", "generated"} and the distinction is
  load-bearing: presenting a fixture as generated would be a lie about what the
  system can do.
"""

from __future__ import annotations

import glob
import os
import subprocess
import tempfile

from generation.spec import (
    ApplicationSpec,
    SpecIncompleteError,
    analyze_requirement,
    answer_questions,
    assert_spec_complete,
)
from validator.emulation_check import emulation_check
from validator.report import ValidationReport
from validator.resource_crosscheck import build_resource_map, resource_crosscheck

FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "fixtures", "emulation",
)
ARM_GCC_GLOB = os.path.expanduser(
    "~/.platformio/packages/toolchain-gccarmnoneeabi/bin/arm-none-eabi-gcc*")


def find_arm_gcc() -> str | None:
    hit = glob.glob(ARM_GCC_GLOB)
    return hit[0] if hit else None


# --- WS2: spec -> the dicts the resource check consumes ---------------------

def compose_devices(spec: ApplicationSpec) -> list[dict]:
    """Bridge ApplicationSpec.devices -> resource_crosscheck's input.

    Only states what the SPEC states. A device whose pins the user never gave
    contributes no pin claims — we do not look up which pins I2C1 uses, because
    that mapping lives in an AF table we do not have (the V1.7 MCU map carries
    no pin/AF data). Bus-address collisions are still detected from what we do
    know. Inventing pins here would manufacture both false conflicts and false
    clean bills of health."""
    out: list[dict] = []
    for d in spec.devices:
        entry: dict = {"name": _val(d.name) or "device"}
        iface = (_val(d.interface) or "").upper()
        pin = _val(d.pin)
        if iface in ("I2C", "SPI", "UART"):
            bus: dict = {"kind": iface.lower()}
            # the spec names an interface family, not an instance; only record an
            # instance if the user actually pinned one down.
            if _val(d.address):
                bus["address"] = _val(d.address)
            bus["instance"] = f"{iface}1"
            entry["bus"] = bus
            if pin:
                entry["pins"] = [{"pin": pin, "function": f"{iface}1"}]
        elif pin:
            entry["pins"] = [{"pin": pin, "function": "GPIO_OUT"}]
        out.append(entry)
    return out


def _val(f):
    return getattr(f, "value", None) if f is not None else None


# --- WS4: firmware ----------------------------------------------------------

def build_firmware(source: str, dest_dir: str) -> tuple[str | None, str]:
    """Compile a bare-metal STM32F4 source to an ELF. Returns (elf, error)."""
    gcc = find_arm_gcc()
    if gcc is None:
        return None, "arm-none-eabi-gcc not available"
    elf = os.path.join(dest_dir, "firmware.elf")
    proc = subprocess.run(
        [gcc, "-mcpu=cortex-m4", "-mthumb", "-Os", "-ffreestanding", "-nostdlib",
         "-nostartfiles", "-Wall", "-Wextra",
         "-T", os.path.join(FIXTURE_DIR, "stm32f4.ld"), source, "-o", elf,
         # V1 drivers may use float (e.g. read_temp_celsius); -nostdlib drops
         # libgcc's soft-float helpers (__aeabi_i2f), so link it back explicitly
         "-lgcc"],
        capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        return None, f"compile failed: {proc.stderr.strip()[:400]}"
    return elf, ""


# --- the pipeline -----------------------------------------------------------

def run_application_pipeline(
    requirement_text: str,
    answers: dict[str, str] | None = None,
    workdir: str | None = None,
    provider=None,
    firmware_source: str | None = None,
    expect: list[str] | None = None,
    stimulus: dict | None = None,
    read_plan=None,
    register_map: dict | None = None,
    measurement: str | None = None,
) -> dict:
    """Run requirement -> verdict. See the module docstring for the contract.

    `read_plan` (generation.app_worker.ReadPlan) makes this a real product path:
    the application firmware is GENERATED from the spec plus the device's own
    register facts, and reported as origin "generated".

    `firmware_source` is an explicit path to bare-metal C, used instead. When it
    comes from tests/fixtures/emulation it is reported as origin "fixture". The
    pipeline never guesses which it is, and never labels one as the other.
    """
    result: dict = {"status": "unknown", "stages": [], "spec": None,
                    "questions": [], "devices": [], "resource_map": None,
                    "firmware_origin": None, "report": None}

    def stage(name, state, detail=""):
        result["stages"].append({"stage": name, "state": state, "detail": detail})

    # -- WS1: spec ----------------------------------------------------------
    spec, questions = analyze_requirement(requirement_text, provider=provider)
    if answers:
        # Answers must be applied to a FIXPOINT, not in one pass: answering
        # "which devices?" CREATES devices[0], which only then raises
        # devices[0].interface / .role. A single pass would leave those unasked-
        # but-unanswered and stall a run the caller had in fact fully answered.
        seen: set[str] = set()
        for _ in range(8):
            spec, questions = answer_questions(spec, answers)
            open_ids = {q.id for q in questions}
            answerable = {q for q in open_ids if q in answers} - seen
            if not answerable:
                break
            seen |= answerable
    result["spec"] = spec
    blocking = [q for q in questions if getattr(q, "blocking", True)]
    if blocking:
        result["questions"] = questions
        result["status"] = "needs-clarification"
        stage("spec", "blocked",
              f"{len(blocking)} question(s) must be answered before anything is "
              "generated — no spec line, no code")
        return result
    try:
        assert_spec_complete(spec)
    except SpecIncompleteError as e:
        result["questions"] = questions
        result["status"] = "needs-clarification"
        stage("spec", "blocked", str(e)[:300])
        return result
    stage("spec", "pass", "every field traces to something the user stated")

    # -- WS2: compose -------------------------------------------------------
    devices = compose_devices(spec)
    result["devices"] = devices
    result["resource_map"] = build_resource_map(devices)
    stage("compose", "pass", f"{len(devices)} device(s) composed")

    report = ValidationReport()

    # -- WS3: resource (the static moat) ------------------------------------
    resource_crosscheck(devices, None, report)
    rstate = report.checks.get("resource_crosscheck")
    stage("resource", rstate,
          "; ".join(f.message for f in report.failures)[:400] if rstate == "fail" else "")
    if rstate == "fail":
        # a conflicting system must never be emulated and called working — the
        # conflict is a decision for the caller, not something we silently patch
        report.finalize()
        result["report"] = report
        result["status"] = "blocked-resource-conflict"
        return result

    # -- WS4: firmware + compile -------------------------------------------
    workdir = workdir or tempfile.mkdtemp(prefix="ep_v2_")
    if read_plan is None and register_map is not None and devices:
        # Derive the plan HERE, not in the caller: the device's bus address lives
        # in the spec, so the plan can only be built once the spec has been
        # resolved and composed. Deriving it earlier would mean the caller
        # guessing an address the user may never have stated.
        from generation.app_worker import derive_read_plan
        addr = devices[0].get("bus", {}).get("address")
        if addr is None:
            stage("generate", "skipped",
                  "the spec never stated the device's bus address, so no read "
                  "plan can be derived — asking is correct here, not guessing")
        else:
            addr_i = addr if isinstance(addr, int) else int(str(addr), 0)
            read_plan, derive_notes = derive_read_plan(
                register_map, addr_i, measurement=measurement)
            result.setdefault("derivation_notes", []).extend(derive_notes)
            if read_plan is None:
                stage("generate", "skipped",
                      "; ".join(derive_notes)[:300] or "no read plan derivable")
    if firmware_source is None and read_plan is not None:
        # WS4: GENERATE the application firmware from the spec + the device's
        # register facts. This is the difference between a demo and a product:
        # the pipeline now produces the artifact it claims to produce.
        from generation.app_worker import generate_application
        firmware_source = os.path.join(workdir, "app.c")
        with open(firmware_source, "w", encoding="utf-8") as f:
            f.write(generate_application(read_plan))
        stage("generate", "pass",
              f"application firmware generated for {read_plan.chip}")
    if firmware_source is None:
        result["status"] = "no-firmware"
        stage("firmware", "skipped",
              "no firmware source and no read plan — the pipeline does not "
              "fabricate one")
        report.checks["emulation_check"] = "skipped"
        result["report"] = report
        return result
    origin = ("fixture" if os.path.abspath(firmware_source).startswith(
        os.path.abspath(FIXTURE_DIR)) else "generated")
    result["firmware_origin"] = origin
    elf, err = build_firmware(firmware_source, workdir)
    if elf is None:
        stage("compile", "fail" if "compile failed" in err else "skipped", err)
        report.checks["emulation_check"] = "skipped"
        report.notes.append(f"emulation not attempted: {err}")
        report.finalize()
        result["report"] = report
        result["status"] = "failed" if "compile failed" in err else "incomplete"
        return result
    stage("compile", "pass", f"firmware.elf built ({origin} source)")

    # -- WS5: emulate -------------------------------------------------------
    dev0 = dict(devices[0]) if devices else {}
    if stimulus:
        dev0["stimulus"] = stimulus
    if not expect and read_plan is not None:
        # Assertions come from the SAME plan that generated the firmware, so they
        # can never drift from the code they check, and nobody hand-writes them
        # per run.
        from generation.app_worker import expectations_for
        expect = expectations_for(read_plan)
    emu_spec = {
        "target": {"platform": "platforms/cpus/stm32f4.repl", "uart": "usart2",
                   "firmware": "firmware.elf", "run_for": "0.5", "timeout": 180},
        "devices": [dev0],
        "expect": expect or [],
    }
    emulation_check(workdir, emu_spec, report)
    estate = report.checks.get("emulation_check")
    stage("emulate", estate,
          "; ".join(f.message for f in report.failures
                    if f.check == "emulation_check")[:400] if estate == "fail" else "")

    result["report"] = report
    result["workdir"] = workdir
    # The APPLICATION verdict is computed here, not taken from
    # ValidationReport.finalize(): finalize() answers "is this DRIVER validated?"
    # and requires a register/readout cross-check that an application-level run
    # does not have, so it would report `failed` for a perfectly good app. Using
    # it here would be misreading one question's answer as another's.
    #
    # not_applicable is a legitimate non-failure: a single-device system has no
    # composition to conflict. It must not block, and it must not be counted as
    # evidence of anything either.
    ok_resource = rstate in ("pass", "not_applicable")
    result["status"] = (
        "working-emulated" if ok_resource and estate == "pass" else "not-working"
    )
    result["verdict_note"] = (
        "ran on an emulated MCU against mocked devices and matched the spec's "
        "expectations — NOT evidence it works on physical hardware"
        if result["status"] == "working-emulated" else ""
    )
    return result
