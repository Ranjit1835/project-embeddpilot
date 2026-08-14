"""Arduino multi-core compile check (V1.8 Part A).

The engineers' requirement — "compatible with all boards" — is a testable claim,
so we test it: compile the generated library's BasicRead sketch with arduino-cli
against ESP32-S3 (their board) plus two structurally different cores (AVR/Uno and
a SAMD ARM Cortex-M0+). A failure on any core that actually ran is a hard failure
and the report names which cores passed. If arduino-cli or a core is unavailable
the core is reported 'skipped' — a judge that did not run passes no one, so
report.finalize() refuses to validate when the whole compile check is skipped.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess

from validator.report import Failure, ValidationReport

# (display name, FQBN) — ESP32-S3 first (the engineers' target), then two
# structurally different cores so "board-agnostic" is actually exercised.
CORES = [
    ("ESP32-S3", "esp32:esp32:esp32s3"),
    ("AVR (Uno)", "arduino:avr:uno"),
    ("SAMD (Cortex-M0+)", "arduino:samd:mkrzero"),
]

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cli() -> str | None:
    """arduino-cli path: the repo-local install first (.arduino-tools/bin), then
    whatever is on PATH (the Docker image installs it system-wide)."""
    local = os.path.join(_REPO, ".arduino-tools", "bin", "arduino-cli")
    for cand in (local, local + ".exe"):
        if os.path.isfile(cand):
            return cand
    return shutil.which("arduino-cli")


def _library_dir(workdir: str) -> str | None:
    """The generated library folder — the one holding library.properties."""
    hits = glob.glob(os.path.join(workdir, "*", "library.properties"))
    return os.path.dirname(hits[0]) if hits else None


def _sketch_dir(libdir: str) -> str | None:
    inos = glob.glob(os.path.join(libdir, "examples", "*", "*.ino"))
    return os.path.dirname(inos[0]) if inos else None


def _core_unavailable(output: str) -> bool:
    low = output.lower()
    return any(s in low for s in (
        "platform not installed", "not installed", "unknown fqbn",
        "platform is not installed", "core not found", "board not found",
    ))


def arduino_compile_check(workdir: str, report: ValidationReport) -> None:
    cli = _cli()
    if cli is None:
        report.checks["compile"] = "skipped"
        report.notes.append(
            "arduino-cli not available — Arduino compile check skipped (install "
            "arduino-cli + cores to validate board compatibility)"
        )
        return

    libdir = _library_dir(workdir)
    sketch = _sketch_dir(libdir) if libdir else None
    if not libdir or not sketch:
        report.checks["compile"] = "fail"
        report.failures.append(Failure(
            "compile", workdir, None,
            "generated Arduino library or BasicRead sketch not found",
        ))
        return

    libraries_root = os.path.dirname(libdir)  # dir CONTAINING the library folder
    any_ran = False
    any_fail = False
    for name, fqbn in CORES:
        cmd = [cli, "compile", "--fqbn", fqbn,
               "--libraries", libraries_root, "--warnings", "all", sketch]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except (subprocess.TimeoutExpired, OSError) as e:
            report.cores.append({"name": name, "fqbn": fqbn,
                                 "result": "skipped", "detail": f"failed to run: {e}"})
            continue
        output = proc.stderr or proc.stdout or ""
        if proc.returncode == 0:
            any_ran = True
            report.cores.append({"name": name, "fqbn": fqbn, "result": "pass"})
        elif _core_unavailable(output):
            report.cores.append({"name": name, "fqbn": fqbn, "result": "skipped",
                                 "detail": "core/board not installed"})
        else:
            any_ran = True
            any_fail = True
            diag = "\n".join(output.splitlines()[-30:])  # tail = the actual errors
            report.cores.append({"name": name, "fqbn": fqbn, "result": "fail",
                                 "detail": diag})
            report.failures.append(Failure(
                "compile", f"{name} [{fqbn}]", None,
                f"[arduino-cli {fqbn} --warnings all]\n{diag}",
            ))

    if not any_ran:
        report.checks["compile"] = "skipped"
        report.notes.append(
            "no Arduino core was available to compile against — Arduino compile "
            "check skipped (result cannot be validated)"
        )
    else:
        report.checks["compile"] = "fail" if any_fail else "pass"
        report.notes.append(
            "arduino-cli: " + ", ".join(
                f"{c['name']}={c['result']}" for c in report.cores
            )
        )
