"""Compile check: zero-warning build of generated sources against a stub HAL.

Toolchain is pluggable and platform-appropriate (V1.5 spec allows this):
ESP32 targets use PlatformIO's xtensa gcc; ARM targets use arm-none-eabi-gcc
if present; otherwise any available C compiler still gives full syntax and
-Wall -Wextra warning coverage for portable C. If nothing is available the
check reports 'skipped' — report.finalize() refuses to validate in that case.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess

from validator.report import Failure, ValidationReport

WARNING_FLAGS = ["-Wall", "-Wextra", "-Werror", "-std=c99"]


def _pio_tool(pattern: str) -> str | None:
    home = os.path.expanduser("~/.platformio/packages")
    hits = glob.glob(os.path.join(home, pattern))
    return hits[0] if hits else None


def _arm() -> str | None:
    return (shutil.which("arm-none-eabi-gcc")
            or _pio_tool("toolchain-gccarmnoneeabi/bin/arm-none-eabi-gcc.exe")
            or _pio_tool("toolchain-gccarmnoneeabi/bin/arm-none-eabi-gcc"))


def _xtensa() -> str | None:
    return (_pio_tool("toolchain-xtensa-esp32/bin/xtensa-esp32-elf-gcc*.exe")
            or _pio_tool("toolchain-xtensa-esp32/bin/xtensa-esp32-elf-gcc*"))


def _avr() -> str | None:
    return (shutil.which("avr-gcc")
            or _pio_tool("toolchain-atmelavr/bin/avr-gcc.exe")
            or _pio_tool("toolchain-atmelavr/bin/avr-gcc"))


def find_compiler(platform: str) -> tuple[str, str] | None:
    """Returns (label, path) for the best compiler for the platform.

    Platform tokens come from the V1.6 dropdown (stm32, esp32, nxp, ti,
    raspberry-pi, avr, cortex-m) or free text ('Other'). ARM-class targets use
    arm-none-eabi-gcc (installed via PlatformIO this round); ESP32 uses the
    xtensa toolchain; AVR uses avr-gcc. If none of the platform-specific tools
    are present we still fall back to any C compiler for full -Wall/-Wextra
    coverage; if nothing is available the check reports 'skipped' and
    report.finalize() refuses to validate.
    """
    plat = platform.lower()
    candidates: list[tuple[str, str | None]] = []
    if "esp32" in plat or "xtensa" in plat:
        candidates.append(("xtensa-esp32-elf-gcc", _xtensa()))
    if any(k in plat for k in ("arm", "stm32", "nrf", "nxp", "cortex", "ti")):
        candidates.append(("arm-none-eabi-gcc", _arm()))
    if "avr" in plat or "arduino" in plat:
        candidates.append(("avr-gcc", _avr()))
    if "raspberry" in plat or "linux" in plat:
        candidates.append(("gcc", shutil.which("gcc")))
    # generic fallbacks — portable C compiles anywhere for warning coverage
    candidates.append(("arm-none-eabi-gcc", _arm()))
    candidates.append(("gcc", shutil.which("gcc")))
    candidates.append(("xtensa-esp32-elf-gcc", _xtensa()))
    for label, path in candidates:
        if path:
            return label, path
    return None


RECOGNIZED = ("esp32", "xtensa", "arm", "stm32", "nrf", "nxp", "cortex", "ti",
              "avr", "arduino", "raspberry", "linux")


def _recognized(platform: str) -> bool:
    plat = platform.lower()
    return any(k in plat for k in RECOGNIZED)


def compile_check(workdir: str, platform: str, report: ValidationReport) -> None:
    found = find_compiler(platform)
    if not found:
        report.checks["compile"] = "skipped"
        report.notes.append("no C compiler available for compile check")
        return
    label, cc = found
    if platform and not _recognized(platform):
        # Priority 3: an 'Other' platform we could not map to a toolchain. Say so
        # plainly instead of compiling with a possibly-mismatched compiler and
        # calling it validated — the label below shows what actually ran.
        report.notes.append(
            f"platform '{platform}' did not map to a known toolchain; compiled "
            f"with {label} for portable-C (-Wall -Wextra) coverage only — it may "
            "not match your target's compiler"
        )

    sources = sorted(glob.glob(os.path.join(workdir, "*.c")))
    if not sources:
        report.checks["compile"] = "fail"
        report.failures.append(Failure("compile", workdir, None, "no .c sources to compile"))
        return

    ok = True
    for src in sources:
        obj = src + ".o"
        cmd = [cc, *WARNING_FLAGS, "-c", src, "-I", workdir, "-o", obj]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except (subprocess.TimeoutExpired, OSError) as e:
            report.checks["compile"] = "skipped"
            report.notes.append(f"compiler {label} failed to run: {e}")
            return
        finally:
            if os.path.exists(obj):
                os.remove(obj)
        if proc.returncode != 0:
            ok = False
            # keep the first ~30 diagnostic lines per file; retries feed on this
            diag = "\n".join((proc.stderr or proc.stdout).splitlines()[:30])
            report.failures.append(Failure(
                "compile", os.path.basename(src), None,
                f"[{label} -Wall -Wextra -Werror]\n{diag}",
            ))
    report.checks["compile"] = "pass" if ok else "fail"
    report.notes.append(f"compiler: {label}")
