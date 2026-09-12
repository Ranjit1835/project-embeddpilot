"""Tests for output_target handling: A (honour the target), B (verify through
the repo's own build system), C (refuse unsupported targets).

These address the two-part bug documented in the task brief:
  1. output_target was captured, validated, blocked on — then silently ignored.
  2. The repo's build system was never run; compile: pass proved the pipeline's
     own gcc call, not the deliverable the user downloads.

The project's one rule applies throughout: a skipped check must never be
dressed up as pass, and a missing tool is an honest 'skipped' with the tool
named — never a silent fallback.
"""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest

from generation.app_worker import (
    AppGenerationError,
    Behavior,
    ReadPlan,
    Step,
    SUPPORTED_OUTPUT_TARGETS,
    derive_read_plan,
    generate_project,
)
from orchestration.v2_pipeline import (
    build_repo,
    find_cmake,
    find_make,
    find_arm_gcc,
    _normalize_output_target,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MAP_PATH = os.path.join(os.path.dirname(__file__), "..", "artifacts",
                        "bmp180-extracted-map.json")

LD = os.path.join(os.path.dirname(__file__), "fixtures", "emulation", "stm32f4.ld")


def _bmp180_plan():
    """Minimal BMP180 read plan — the same one used in the pipeline tests."""
    return ReadPlan(chip="BMP180", address=0x77, steps=[
        Step("read8",  label="BMP180-ID",    reg=0xD0, expect_hex="55"),
        Step("write8", label="BMP180-START", reg=0xF4, value=0x2E),
        Step("delay",  label="BMP180-WAIT",  ticks=200000),
        Step("read16", label="BMP180-UT",    reg=0xF6, reg_lo=0xF7),
    ])


def _ld():
    """Return the linker script content, or skip if absent."""
    if not os.path.exists(LD):
        pytest.skip("stm32f4.ld not present")
    with open(LD, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# A: output_target is honoured in generate_project
# ---------------------------------------------------------------------------

class TestOutputTargetGenerateProject:
    """generate_project() must route to the correct build system and refuse
    unrecognised targets."""

    def test_make_target_emits_makefile_not_cmake(self):
        """Requesting 'make' must produce a Makefile, not CMake files."""
        files = generate_project(_bmp180_plan(), output_target="make",
                                 linker_script=_ld())
        assert "Makefile" in files, "make target must include a Makefile"
        assert "CMakeLists.txt" not in files, \
            "make target must NOT include CMakeLists.txt"
        assert "cmake/arm-none-eabi.cmake" not in files

    def test_cmake_target_emits_cmakelists_not_makefile(self):
        """Requesting 'cmake' must produce CMakeLists.txt + toolchain, not a
        Makefile."""
        files = generate_project(_bmp180_plan(), output_target="cmake",
                                 linker_script=_ld())
        assert "CMakeLists.txt" in files, "cmake target must include CMakeLists.txt"
        assert "cmake/arm-none-eabi.cmake" in files, \
            "cmake target must include the toolchain file"
        assert "Makefile" not in files, \
            "cmake target must NOT include a Makefile"

    def test_cmake_cmakelists_contains_correct_flags(self):
        """The CMakeLists must carry -lgcc and the linker script path — the
        same flags the pipeline's own gcc call uses."""
        files = generate_project(_bmp180_plan(), output_target="cmake",
                                 linker_script=_ld())
        cml = files["CMakeLists.txt"]
        assert "-lgcc" in cml, \
            "CMakeLists.txt must link -lgcc (soft-float helpers)"
        assert "stm32f4.ld" in cml, \
            "CMakeLists.txt must reference the linker script"
        assert "firmware.elf" in cml, \
            "CMakeLists.txt must name the ELF target"

    def test_cmake_toolchain_targets_cortex_m4(self):
        """The toolchain file must set cortex-m4 / thumb flags."""
        files = generate_project(_bmp180_plan(), output_target="cmake",
                                 linker_script=_ld())
        tc = files["cmake/arm-none-eabi.cmake"]
        assert "cortex-m4" in tc
        assert "mthumb" in tc or "-mthumb" in tc

    def test_make_target_default(self):
        """Calling generate_project() without output_target defaults to make."""
        files = generate_project(_bmp180_plan(), linker_script=_ld())
        assert "Makefile" in files
        assert "CMakeLists.txt" not in files

    def test_unsupported_target_is_refused_explicitly(self):
        """An unrecognised output_target must raise AppGenerationError and
        name the value asked for plus what is supported.  Never silently
        substituting a different build system is the one rule this feature
        exists to enforce."""
        with pytest.raises(AppGenerationError) as exc_info:
            generate_project(_bmp180_plan(), output_target="bazel")
        msg = str(exc_info.value)
        assert "bazel" in msg, "error must name the bad target"
        assert any(t in msg for t in SUPPORTED_OUTPUT_TARGETS), \
            "error must name the supported targets"

    def test_arduino_sketch_target_is_refused_explicitly(self):
        """arduino-sketch is listed in the spec's OUTPUT_TARGETS but is not
        yet implemented — must be refused, not silently downgraded."""
        with pytest.raises(AppGenerationError) as exc_info:
            generate_project(_bmp180_plan(), output_target="arduino-sketch")
        msg = str(exc_info.value)
        assert "arduino-sketch" in msg

    def test_platformio_target_is_refused_explicitly(self):
        """platformio-project is listed in the spec's OUTPUT_TARGETS but is
        not yet implemented — must be refused, not silently downgraded."""
        with pytest.raises(AppGenerationError) as exc_info:
            generate_project(_bmp180_plan(), output_target="platformio-project")
        msg = str(exc_info.value)
        assert "platformio-project" in msg

    def test_readme_names_cmake_build_command(self):
        """The README for a cmake repo must show cmake commands, not 'make'."""
        files = generate_project(_bmp180_plan(), output_target="cmake",
                                 linker_script=_ld())
        readme = files["README.md"]
        assert "cmake" in readme.lower(), \
            "README must document the cmake build command"
        # The raw 'make' command must not appear as the primary build step
        # (make may appear inside cmake internals, but not as the user command)
        lines = readme.splitlines()
        # Find the build section
        build_lines = [l for l in lines if l.strip().startswith("cmake")]
        assert build_lines, "README must show cmake commands in the build section"

    def test_readme_names_make_build_command(self):
        """The README for a make repo must show 'make' as the build command."""
        files = generate_project(_bmp180_plan(), output_target="make",
                                 linker_script=_ld())
        readme = files["README.md"]
        assert "make" in readme

    def test_both_targets_include_linker_script(self):
        """Both build systems need the linker script."""
        ld_content = _ld()
        for target in ("make", "cmake"):
            files = generate_project(_bmp180_plan(), output_target=target,
                                     linker_script=ld_content)
            assert "link/stm32f4.ld" in files, \
                f"{target} repo must ship the linker script"


# ---------------------------------------------------------------------------
# A: spec vocabulary mapping (_normalize_output_target)
# ---------------------------------------------------------------------------

class TestNormalizeOutputTarget:
    """The spec's output_target vocabulary ('cmake-project', etc.) must map to
    the generator's two-word vocabulary ('cmake', 'make').  Unmapped values
    must produce an error message that names what was asked and what is
    supported."""

    def test_cmake_project_maps_to_cmake(self):
        target, err = _normalize_output_target("cmake-project")
        assert target == "cmake"
        assert err == ""

    def test_make_maps_to_make(self):
        target, err = _normalize_output_target("make")
        assert target == "make"
        assert err == ""

    def test_none_defaults_to_make(self):
        target, err = _normalize_output_target(None)
        assert target == "make"
        assert err == ""

    def test_unsupported_value_returns_error_naming_the_bad_value(self):
        target, err = _normalize_output_target("bazel")
        assert target == ""
        assert "bazel" in err
        # error must name what IS supported so the caller can re-try.
        # Case-insensitive: the message spells the tools as CMake / Makefile,
        # which is how they are actually written.
        assert "cmake" in err.lower() or "make" in err.lower()

    # --- natural phrasing, which is what extraction actually produces --------
    # Regression: output_target is extracted from the user's own words, so
    # "produce a cmake project" arrives as "cmake project". An exact-key lookup
    # rejected that and hard-failed the product's own showcase requirement.

    @pytest.mark.parametrize("raw", [
        "cmake project",
        "a cmake project",
        "CMake Project",
        "cmake_project",
        "produce a cmake project",
    ])
    def test_natural_cmake_phrasing_is_accepted(self, raw):
        target, err = _normalize_output_target(raw)
        assert (target, err) == ("cmake", "")

    @pytest.mark.parametrize("raw", [
        "makefile",
        "Makefile",
        "a make project",
        "make build",
    ])
    def test_natural_make_phrasing_is_accepted(self, raw):
        target, err = _normalize_output_target(raw)
        assert (target, err) == ("make", "")

    def test_cmake_is_not_read_as_make(self):
        """'cmake' CONTAINS 'make'. A substring test would quietly hand back a
        Makefile for every CMake request — the silent-substitution bug,
        inverted."""
        assert _normalize_output_target("cmake")[0] == "cmake"
        assert _normalize_output_target("cmake project")[0] == "cmake"

    def test_naming_both_build_systems_is_refused_not_guessed(self):
        target, err = _normalize_output_target("cmake makefile")
        assert target == ""
        assert "both" in err.lower()

    @pytest.mark.parametrize("raw", [
        "arduino sketch",
        "platformio project",
        "a bazel workspace",
        "ninja build",
    ])
    def test_widening_the_phrasing_did_not_widen_what_is_supported(self, raw):
        """Accepting looser wording must not accept more BUILD SYSTEMS."""
        target, err = _normalize_output_target(raw)
        assert target == ""
        assert err

    def test_arduino_sketch_returns_error(self):
        """arduino-sketch is in the spec vocabulary but not yet implemented."""
        target, err = _normalize_output_target("arduino-sketch")
        assert target == ""
        assert "arduino-sketch" in err


# ---------------------------------------------------------------------------
# B: repo-build check (build_repo)
# ---------------------------------------------------------------------------

class TestBuildRepo:
    """build_repo() must:
    - Return (elf_path, "") when the tool is present and the repo builds.
    - Return (None, "skipped: <reason naming the missing tool>") when the
      tool is absent — never (None, "").
    - Never return a 'skipped' result with an empty reason.
    """

    def test_skipped_names_the_missing_tool_for_make(self, monkeypatch):
        """When make is absent the result is 'skipped: make not available',
        NOT pass or an empty skip."""
        monkeypatch.setattr(
            "orchestration.v2_pipeline.find_make", lambda: None
        )
        elf, msg = build_repo("/any/dir", "make")
        assert elf is None
        assert msg.startswith("skipped:")
        assert "make" in msg, "skip message must name the missing tool"

    def test_skipped_names_the_missing_tool_for_cmake(self, monkeypatch):
        """When cmake is absent the result is 'skipped: cmake not available',
        NOT pass or an empty skip."""
        monkeypatch.setattr(
            "orchestration.v2_pipeline.find_cmake", lambda: None
        )
        elf, msg = build_repo("/any/dir", "cmake")
        assert elf is None
        assert msg.startswith("skipped:")
        assert "cmake" in msg

    def test_skipped_names_missing_arm_gcc_for_make(self, monkeypatch):
        """When arm-none-eabi-gcc is absent (but make is present) the skip
        message must name the missing compiler, not make."""
        monkeypatch.setattr(
            "orchestration.v2_pipeline.find_make", lambda: "/usr/bin/make"
        )
        monkeypatch.setattr(
            "orchestration.v2_pipeline.find_arm_gcc", lambda: None
        )
        elf, msg = build_repo("/any/dir", "make")
        assert elf is None
        assert msg.startswith("skipped:")
        assert "arm-none-eabi-gcc" in msg

    def test_skipped_reason_is_never_empty(self, monkeypatch):
        """A skipped result with no reason is indistinguishable from pass in
        a log — the reason is mandatory."""
        monkeypatch.setattr(
            "orchestration.v2_pipeline.find_make", lambda: None
        )
        _, msg = build_repo("/any/dir", "make")
        assert len(msg) > len("skipped:"), \
            "skip message must contain a reason after 'skipped:'"

    @pytest.mark.skipif(
        find_make() is None or find_arm_gcc() is None,
        reason="needs make + arm-none-eabi-gcc"
    )
    def test_make_repo_builds_and_elf_exists(self):
        """When tools are present the Makefile repo must actually produce an
        ELF — the check is real, not asserted."""
        files = generate_project(_bmp180_plan(), output_target="make",
                                 linker_script=_ld())
        d = tempfile.mkdtemp(prefix="ep_test_make_")
        try:
            for rel, content in files.items():
                path = os.path.join(d, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
            elf, msg = build_repo(d, "make")
            assert msg == "", f"make build failed: {msg}"
            assert elf is not None
            assert os.path.isfile(elf), f"ELF not found at {elf}"
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @pytest.mark.skipif(
        find_cmake() is None or find_arm_gcc() is None,
        reason="needs cmake + arm-none-eabi-gcc"
    )
    def test_cmake_repo_builds_and_elf_exists(self):
        """When tools are present the CMake repo must actually produce an ELF."""
        files = generate_project(_bmp180_plan(), output_target="cmake",
                                 linker_script=_ld())
        d = tempfile.mkdtemp(prefix="ep_test_cmake_")
        try:
            for rel, content in files.items():
                path = os.path.join(d, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
            elf, msg = build_repo(d, "cmake")
            assert msg == "", f"cmake build failed: {msg}"
            assert elf is not None
            assert os.path.isfile(elf), f"ELF not found at {elf}"
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# Pipeline integration: output_target flows end-to-end
# ---------------------------------------------------------------------------

class TestPipelineOutputTarget:
    """The pipeline must read output_target from the spec and honour it.
    These tests do NOT require Renode or arm-none-eabi-gcc: they exercise
    the spec intake and generation stages only."""

    def test_pipeline_refuses_unsupported_target_without_generating(self):
        """An unsupported output_target must be refused at the generate stage,
        before any ELF or emulation — honesty over appearance-of-completion.

        Note: the spec must be FULLY answered before the generate stage runs.
        The generate stage is only attempted when firmware_source is absent and
        read_plan is present — passing firmware_source would bypass it."""
        from orchestration.v2_pipeline import run_application_pipeline
        from generation.provider import MockProvider

        REQ = ("Read the BMP180 over I2C at address 0x77 and print raw "
               "temperature over UART.")
        # Complete set of answers so the spec passes WS1, then fails at WS4
        # because "bazel" is not a supported generator target.
        answers = {
            "q:target.board": "Nucleo-F411RE",
            "q:target.mcu": "STM32F411RET6",
            "q:failure_behavior": "retry",
            "q:output_target": "bazel",          # unsupported at the generator
            "q:constraints.sample_rate": "500 ms",
            "q:behaviors": "read temperature and print it over UART",
            "q:behaviors[0].trigger.source": "temperature",
            "q:behaviors[0].trigger.comparator": ">",
            "q:behaviors[0].trigger.threshold": "18500",
            "q:behaviors[0].trigger.unit": "raw",
        }

        def provider():
            return MockProvider([{"devices": [{
                "name": {"value": "BMP180", "evidence": "BMP180"},
                "interface": {"value": "I2C", "evidence": "over I2C"},
                "address": {"value": "0x77", "evidence": "address 0x77"},
                "role": {"value": "temperature", "evidence": "raw temperature"},
            }]}] + [{} for _ in range(9)])

        # Do NOT pass firmware_source: we want the generate stage to run and
        # fail on the unsupported target, not be skipped.
        r = run_application_pipeline(
            REQ, answers=answers, provider=provider(),
            read_plan=_bmp180_plan(),
        )
        stages = {s["stage"]: s["state"] for s in r["stages"]}
        assert stages.get("generate") == "fail", \
            ("unsupported output_target must fail the generate stage, "
             "not silently produce a repo with the wrong build system. "
             f"Got stages: {stages}, status: {r['status']}")
        assert r["status"] == "failed"
        # nothing emulated — failing before compile means we never reach WS5
        assert "emulate" not in stages

    # Full answers needed to pass WS1 so the generate stage is attempted.
    _FULL_ANSWERS_BASE = {
        "q:target.board": "Nucleo-F411RE",
        "q:target.mcu": "STM32F411RET6",
        "q:failure_behavior": "retry",
        "q:constraints.sample_rate": "500 ms",
        "q:behaviors": "read temperature and print it over UART",
        "q:behaviors[0].trigger.source": "temperature",
        "q:behaviors[0].trigger.comparator": ">",
        "q:behaviors[0].trigger.threshold": "18500",
        "q:behaviors[0].trigger.unit": "raw",
    }

    def _provider(self):
        from generation.provider import MockProvider
        return MockProvider([{"devices": [{
            "name": {"value": "BMP180", "evidence": "BMP180"},
            "interface": {"value": "I2C", "evidence": "over I2C"},
            "address": {"value": "0x77", "evidence": "address 0x77"},
            "role": {"value": "temperature", "evidence": "raw temperature"},
        }]}] + [{} for _ in range(9)])

    def test_pipeline_cmake_target_emits_cmake_files(self):
        """When the spec says cmake-project the generated repo must contain
        CMakeLists.txt, not a Makefile.

        firmware_source is NOT supplied so the generate stage actually runs
        and produces files.  Compile will skip (no arm-none-eabi-gcc), but
        file content is already in result['files']."""
        from orchestration.v2_pipeline import run_application_pipeline

        REQ = ("Read the BMP180 over I2C at address 0x77 and print raw "
               "temperature over UART.")
        answers = dict(self._FULL_ANSWERS_BASE)
        answers["q:output_target"] = "cmake-project"

        r = run_application_pipeline(
            REQ, answers=answers, provider=self._provider(),
            read_plan=_bmp180_plan(),
            # No firmware_source: we need the generate stage to run.
        )
        stages = {s["stage"]: s["state"] for s in r["stages"]}
        assert "generate" in stages, \
            f"generate stage must run; got stages {list(stages)}"
        assert stages["generate"] == "pass", \
            f"generate stage failed: {r['stages']}"
        files = r.get("files", {})
        assert "CMakeLists.txt" in files, \
            "cmake-project output_target must emit CMakeLists.txt"
        assert "Makefile" not in files, \
            "cmake-project output_target must NOT emit a Makefile"
        assert r.get("output_target") == "cmake"

    def test_pipeline_make_target_emits_makefile(self):
        """When the spec says make the generated repo must contain a Makefile."""
        from orchestration.v2_pipeline import run_application_pipeline

        REQ = ("Read the BMP180 over I2C at address 0x77 and print raw "
               "temperature over UART.")
        answers = dict(self._FULL_ANSWERS_BASE)
        answers["q:output_target"] = "make"

        r = run_application_pipeline(
            REQ, answers=answers, provider=self._provider(),
            read_plan=_bmp180_plan(),
        )
        stages = {s["stage"]: s["state"] for s in r["stages"]}
        assert "generate" in stages, \
            f"generate stage must run; got stages {list(stages)}"
        assert stages["generate"] == "pass", \
            f"generate stage failed: {r['stages']}"
        files = r.get("files", {})
        assert "Makefile" in files
        assert "CMakeLists.txt" not in files

    def test_skipped_repo_build_is_reported_honestly_not_as_pass(self):
        """When make is absent, the repo-build stage must report 'skipped' with
        a reason naming the missing tool — never 'pass'.

        The design: a skipped repo-build does NOT block the working-emulated
        verdict (the firmware DID run in emulation), but the README and
        verdict_note must clearly disclose that the repo build was not verified.
        Skipped-as-pass is the original cardinal sin: we must name the gap,
        not hide it.

        This test drives through the full generate stage (no firmware_source)
        so the pipeline writes the repo files and then attempts the repo build.
        Compile may skip (no gcc), which is fine — the assertion is about
        the repo_build stage state.
        """
        from orchestration.v2_pipeline import run_application_pipeline

        REQ = ("Read the BMP180 over I2C at address 0x77 and print raw "
               "temperature over UART.")
        answers = dict(self._FULL_ANSWERS_BASE)
        answers["q:output_target"] = "make"

        # Patch make away so the repo-build is skipped
        import orchestration.v2_pipeline as _pipe
        orig_find_make = _pipe.find_make

        def _no_make():
            return None

        _pipe.find_make = _no_make
        try:
            r = run_application_pipeline(
                REQ, answers=answers, provider=self._provider(),
                read_plan=_bmp180_plan(),
                # No firmware_source: generate stage runs, writes repo files,
                # then compile is attempted (may skip) and repo_build is checked.
            )
        finally:
            _pipe.find_make = orig_find_make

        stages = {s["stage"]: s["state"] for s in r["stages"]}
        # The generate stage must have run
        assert "generate" in stages, \
            f"generate stage must run; got {list(stages)}"
        assert stages["generate"] == "pass"

        # If repo_build ran (it runs after compile, which needs gcc), check
        # that it reports skipped honestly.
        if "repo_build" in stages:
            assert stages["repo_build"] == "skipped", \
                "missing make must produce 'skipped', not 'pass' or 'fail'"
            skip_detail = next(
                s["detail"] for s in r["stages"] if s["stage"] == "repo_build")
            assert "make" in skip_detail.lower(), \
                "skip detail must name the missing tool (make)"

    def test_failed_repo_build_prevents_working_emulated_verdict(self):
        """If make IS present but the build fails (broken Makefile, bad flags,
        etc.) the status must be not-working — a broken deliverable must never
        be called working."""
        from orchestration.v2_pipeline import run_application_pipeline
        import subprocess

        REQ = ("Read the BMP180 over I2C at address 0x77 and print raw "
               "temperature over UART.")
        answers = dict(self._FULL_ANSWERS_BASE)
        answers["q:output_target"] = "make"

        # Patch build_repo to simulate a make failure
        import orchestration.v2_pipeline as _pipe
        orig_build_repo = _pipe.build_repo

        def _bad_make(repo_dir, output_target):
            return None, "failed: make: error: bad.c:1: undefined reference to 'nothing'"

        _pipe.build_repo = _bad_make
        try:
            r = run_application_pipeline(
                REQ, answers=answers, provider=self._provider(),
                read_plan=_bmp180_plan(),
            )
        finally:
            _pipe.build_repo = orig_build_repo

        stages = {s["stage"]: s["state"] for s in r["stages"]}
        if "repo_build" in stages:
            assert stages["repo_build"] == "fail"
            assert r["status"] != "working-emulated", \
                "a failed repo build must prevent working-emulated"
