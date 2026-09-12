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
import re
import shutil
import subprocess
import tempfile

from generation.spec import (
    ApplicationSpec,
    SpecIncompleteError,
    analyze_requirement,
    answer_questions,
    assert_spec_complete,
)
from orchestration.targets import (
    UnsupportedTargetError,
    assert_target_supported,
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


def _linker_script() -> str:
    """The linker script the generated repo ships so it builds standalone.

    It is a BUILD INPUT that happens to live under tests/fixtures — a generated
    repo that assumed the user already had one would not actually build, which
    is the whole point of shipping a repo rather than a source file."""
    path = os.path.join(FIXTURE_DIR, "stm32f4.ld")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def find_arm_gcc() -> str | None:
    """Path to arm-none-eabi-gcc, or None.

    Order: explicit override, the local PlatformIO toolchain, then PATH. PATH
    matters and was the omission that mattered: the deployed image installs the
    compiler via apt at /usr/bin, so globbing only ~/.platformio made the
    compile stage report "arm-none-eabi-gcc not available" in production while
    the compiler sat right there. Honest degradation is worthless if it fires
    for a reason that is not true.
    """
    override = os.environ.get("EMBEDDPILOT_ARM_GCC")
    if override and os.path.isfile(override):
        return override
    hit = sorted(glob.glob(ARM_GCC_GLOB))
    if hit:
        return hit[-1]
    return shutil.which("arm-none-eabi-gcc")


def find_make() -> str | None:
    """Path to make (or gmake), or None."""
    return shutil.which("make") or shutil.which("gmake")


def find_cmake() -> str | None:
    """Path to cmake, or None."""
    return shutil.which("cmake")


# Map from the spec's OUTPUT_TARGETS vocabulary to the generator's internal
# two-word vocabulary.  Entries map spec -> generator.  Any spec value that
# has no entry is unsupported and must be refused explicitly.
_SPEC_TARGET_MAP = {
    "cmake-project": "cmake",
    "cmake":         "cmake",
    "make":          "make",
    "makefile":      "make",
    # Arduino and PlatformIO are listed as options in the spec so the UI can
    # offer them, but they are not yet implemented in the generator.  They must
    # be refused explicitly rather than silently substituted.
}
_SUPPORTED_SPEC_TARGETS = tuple(_SPEC_TARGET_MAP)


_CMAKE_WORDS = frozenset({"cmake"})
_MAKE_WORDS = frozenset({"make", "makefile", "gnumake"})


def _normalize_output_target(raw: str | None) -> tuple[str, str]:
    """Map the spec's output_target string to the generator's vocabulary.

    Returns (generator_target, error_message).  On success error_message is "".
    On failure generator_target is "" and error_message names what was asked
    and what is supported.

    Matched on WORDS, not on an exact key. `output_target` is extracted from
    what the user actually wrote, so "produce a cmake project" legitimately
    arrives as "cmake project" — and an exact-key lookup rejected that, which
    hard-failed the product's own showcase requirement. Words rather than
    substrings because "cmake" contains "make"; a substring test would read
    every CMake request as a Makefile request, which is the silent-substitution
    bug this guard exists to prevent, inverted.

    A value naming neither is still REFUSED. Widening the phrasing we accept
    must not widen the set of build systems we claim to produce.
    """
    if raw is None:
        return "make", ""  # default: Makefile

    tokens = {t for t in re.split(r"[^a-z0-9]+", str(raw).strip().lower()) if t}
    wants_cmake = bool(tokens & _CMAKE_WORDS)
    wants_make = bool(tokens & _MAKE_WORDS)

    if wants_cmake and wants_make:
        return "", (
            f"output_target {raw!r} names both CMake and Make. Pick one — "
            f"guessing which you meant is how a build system gets silently "
            f"substituted."
        )
    if wants_cmake:
        return "cmake", ""
    if wants_make:
        return "make", ""
    return "", (
        f"output_target {raw!r} is not supported by this generator. "
        f"Supported: a CMake project, or a Makefile. "
        f"Refusing to substitute a different build system — that is the bug "
        f"this guard exists to prevent."
    )


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


# --- WS4b: build through the repo's own build system -----------------------

def build_repo(repo_dir: str, output_target: str) -> tuple[str | None, str]:
    """Build the generated repo through its own build system.

    This is the check the spec asked for: 'prove B by running it, not by
    asserting it'.  A compiled `main.c` proves the source is valid C; it does
    NOT prove the Makefile/CMakeLists.txt is wired correctly — that requires
    actually running the build system.

    Returns (elf_path, skip_or_error_msg):
      - (path, "")        — build succeeded, ELF confirmed present
      - (None, "skipped: <reason>")  — tool absent, reported honestly
      - (None, "failed: <stderr>")   — tool present but build failed
    """
    import tempfile as _tmp

    if output_target == "cmake":
        cmake = find_cmake()
        if cmake is None:
            return None, "skipped: cmake not available on this machine"
        arm_gcc = find_arm_gcc()
        if arm_gcc is None:
            return None, "skipped: arm-none-eabi-gcc not available"
        build_dir = _tmp.mkdtemp(prefix="ep_cmake_")
        toolchain = os.path.join(repo_dir, "cmake", "arm-none-eabi.cmake")
        # Configure
        cfg = subprocess.run(
            [cmake,
             f"-DCMAKE_TOOLCHAIN_FILE={toolchain}",
             f"-DCMAKE_C_COMPILER={arm_gcc}",
             "-S", repo_dir,
             "-B", build_dir],
            capture_output=True, text=True, timeout=120,
        )
        if cfg.returncode != 0:
            return None, f"failed: cmake configure: {cfg.stderr.strip()[:400]}"
        # Build
        bld = subprocess.run(
            [cmake, "--build", build_dir],
            capture_output=True, text=True, timeout=240,
        )
        if bld.returncode != 0:
            return None, f"failed: cmake build: {bld.stderr.strip()[:400]}"
        elf = os.path.join(build_dir, "firmware.elf")
        if not os.path.isfile(elf):
            return None, f"failed: cmake build succeeded but firmware.elf not found in {build_dir}"
        return elf, ""

    else:  # make
        make = find_make()
        if make is None:
            return None, "skipped: make not available on this machine"
        arm_gcc = find_arm_gcc()
        if arm_gcc is None:
            return None, "skipped: arm-none-eabi-gcc not available"
        bld = subprocess.run(
            [make, "-C", repo_dir],
            capture_output=True, text=True, timeout=240,
        )
        if bld.returncode != 0:
            return None, f"failed: make: {bld.stderr.strip()[:400]}"
        elf = os.path.join(repo_dir, "build", "firmware.elf")
        if not os.path.isfile(elf):
            return None, f"failed: make succeeded but build/firmware.elf not found"
        return elf, ""


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
    behavior=None,
    samples: int = 1,
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

    # -- WS1b: can we actually build for the part they named? ---------------
    # Everything below is STM32F4 and nothing else: the scaffold emits STM32F4
    # peripheral code, the linker script is stm32f4.ld, the compiler runs with
    # -mcpu=cortex-m4 and the emulator loads stm32f4.repl. None of that was
    # ever checked against the MCU the user stated — which intake REQUIRES
    # them to state — so a requirement naming an ESP32 (Xtensa, not even ARM)
    # was accepted with zero blocking questions, built as an STM32F4, shipped
    # an stm32f4.ld inside the ESP32 project, and returned `working-emulated`.
    # A green verdict for the wrong architecture is the worst thing this
    # pipeline can emit, so refuse before anything is generated.
    mcu = spec.target.mcu.value if spec.target.mcu else None
    board = spec.target.board.value if spec.target.board else None
    try:
        assert_target_supported(mcu, board)
    except UnsupportedTargetError as exc:
        result["status"] = "blocked-unsupported-target"
        stage("target", "fail", str(exc)[:400])
        return result
    stage("target", "pass", f"{mcu} is a target this pipeline can build for")

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
        # WS4: GENERATE the application. The product's claim is a complete
        # REPO — src/, a Makefile or CMakeLists.txt, the linker script and a
        # README that states what was and was not verified — so emit the repo,
        # not a loose .c file.
        from generation.app_worker import generate_project, AppGenerationError

        # Resolve output_target from the spec.  A value that was captured,
        # validated and then silently ignored is the original bug this task
        # exists to fix: the spec requires it, the generator must honour it.
        raw_target = getattr(
            getattr(spec, "output_target", None), "value", None
        )
        gen_target, target_err = _normalize_output_target(raw_target)
        if target_err:
            stage("generate", "fail", target_err)
            report.finalize()
            result["report"] = report
            result["status"] = "failed"
            return result

        try:
            files = generate_project(
                read_plan, behavior=behavior, samples=samples,
                has_math_oracle=bool((register_map or {}).get("math_oracle")),
                linker_script=_linker_script(),
                output_target=gen_target,
            )
        except AppGenerationError as e:
            stage("generate", "fail", str(e)[:300])
            report.finalize()
            result["report"] = report
            result["status"] = "failed"
            return result

        for rel, content in files.items():
            path = os.path.join(workdir, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
        # the caller gets the repo itself, not just a verdict about it
        result["files"] = files
        result["output_target"] = gen_target
        firmware_source = os.path.join(workdir, "src", "main.c")
        stage("generate", "pass",
              f"application repo generated for {read_plan.chip} "
              f"({len(files)} files, {gen_target} build system)")
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

    # -- WS4c: build through the repo's own build system --------------------
    # This is point B of the bug report: the pipeline PROVED its own gcc call
    # worked, but never ran the Makefile / CMakeLists the user downloads. A
    # repo that doesn't build through its own build system is not a deliverable.
    #
    # The check is only meaningful for generated repos — for hand-written
    # fixtures there is no "repo build system" to verify.
    #
    # Honesty constraint: if the build tool is absent the check is `skipped`
    # with a reason that names the missing tool.  A skipped repo build must
    # NOT contribute to a `working-emulated` verdict.
    repo_build_state = "not_applicable"
    repo_build_skip_reason = ""
    if origin == "generated" and result.get("output_target"):
        gen_target = result["output_target"]
        _repo_elf, repo_msg = build_repo(workdir, gen_target)
        if repo_msg.startswith("skipped:"):
            repo_build_state = "skipped"
            repo_build_skip_reason = repo_msg[len("skipped: "):]
            stage("repo_build", "skipped", repo_msg)
        elif repo_msg.startswith("failed:"):
            repo_build_state = "fail"
            stage("repo_build", "fail", repo_msg)
        else:
            repo_build_state = "pass"
            stage("repo_build", "pass",
                  f"repo built through {gen_target} build system -> ELF confirmed")
        # Propagate the result back into the README so it states what was
        # actually verified.  The files dict is already written to disk; we
        # patch the in-memory entry and rewrite.
        if "files" in result and "README.md" in result["files"]:
            from generation.app_worker import _readme as _gen_readme
            _v = dict(result.get("_verified_meta", {}))
            if repo_build_state == "pass":
                _v["repo_build"] = "pass"
            elif repo_build_state == "skipped":
                _v["repo_build"] = "skipped"
                _v["repo_build_skip_reason"] = repo_build_skip_reason
            else:
                _v["repo_build"] = "fail"
            updated_readme = _gen_readme(
                read_plan, behavior, _v, output_target=gen_target)
            result["files"]["README.md"] = updated_readme
            readme_path = os.path.join(workdir, "README.md")
            with open(readme_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(updated_readme)

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
    #
    # Honesty constraint on repo_build:
    #   pass        — the repo built through its own build system; ELF confirmed.
    #   skipped     — the build tool was absent; the check could not run.  This is
    #                 honest: it names exactly what was not tested and why.
    #   not_applicable — not a generated repo (e.g. a hand-written fixture); the
    #                    build system check is irrelevant.
    #   fail        — the tool was present but the build failed.
    #
    # `working-emulated` requires that repo_build is NOT fail.  A `skipped`
    # result does not block the verdict — the README and verdict_note clearly
    # state that the repo build was not verified, which is the honest record.
    # A failed repo build (tool present but build broken) is a hard blocker:
    # the deliverable does not work and we must not call it working.
    ok_resource = rstate in ("pass", "not_applicable")
    repo_ok = repo_build_state in ("pass", "not_applicable", "skipped")
    result["status"] = (
        "working-emulated"
        if ok_resource and estate == "pass" and repo_ok
        else "not-working"
    )
    if result["status"] == "working-emulated":
        if repo_build_state == "skipped":
            result["verdict_note"] = (
                "ran on an emulated MCU against mocked devices and matched the "
                "spec's expectations — NOT evidence it works on physical hardware. "
                f"Repo build via build system was NOT verified: "
                f"{repo_build_skip_reason}"
            )
        else:
            result["verdict_note"] = (
                "ran on an emulated MCU against mocked devices and matched the spec's "
                "expectations — NOT evidence it works on physical hardware"
            )
    elif repo_build_state == "fail":
        result["verdict_note"] = (
            "repo build failed through its own build system — "
            "the deliverable does not build; fix the build system before shipping"
        )
    else:
        result["verdict_note"] = ""
    return result
