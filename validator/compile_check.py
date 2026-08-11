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


def _preferred_toolchains(platform: str) -> list[tuple[str, str | None]]:
    """The platform's native toolchain candidates, most-specific first, each
    paired with its resolved path (None if not installed). Order/labels are the
    single source of truth for both compiler selection and the requested-vs-
    actual toolchain labeling (Fix 4)."""
    plat = platform.lower()
    preferred: list[tuple[str, str | None]] = []
    if "esp32" in plat or "xtensa" in plat:
        preferred.append(("xtensa-esp32-elf-gcc", _xtensa()))
    if any(k in plat for k in ("arm", "stm32", "nrf", "nxp", "cortex", "ti")):
        preferred.append(("arm-none-eabi-gcc", _arm()))
    if "avr" in plat or "arduino" in plat:
        preferred.append(("avr-gcc", _avr()))
    if "raspberry" in plat or "linux" in plat:
        preferred.append(("gcc", shutil.which("gcc")))
    return preferred


def requested_toolchain(platform: str) -> str | None:
    """The label of the platform's own (target-accurate) toolchain, whether or
    not it is installed — used to name what the compile SHOULD have used when a
    fallback compiler actually ran. None for free-text ('Other') platforms."""
    cands = _preferred_toolchains(platform)
    return cands[0][0] if cands else None


def find_compiler(platform: str) -> tuple[str, str, bool] | None:
    """Returns (label, path, exact) for the best compiler for the platform.

    `exact` is True when the compiler is the platform's own toolchain, False
    when we fell back to a generic C compiler for portable warning coverage
    (e.g. esp32 in an environment with no xtensa toolchain — the Docker image
    ships arm-none-eabi-gcc, not xtensa). compile_check surfaces that
    substitution in a note so a fallback build is never silently presented as
    a native-toolchain build.

    Platform tokens come from the V1.6 dropdown (stm32, esp32, nxp, ti,
    raspberry-pi, avr, cortex-m) or free text ('Other'). If none of the
    platform-specific tools are present we still fall back to any C compiler;
    if nothing is available the check reports 'skipped' and report.finalize()
    refuses to validate.
    """
    for label, path in _preferred_toolchains(platform):
        if path:
            return label, path, True
    # generic fallbacks — portable C compiles anywhere for warning coverage
    for label, path in (("arm-none-eabi-gcc", _arm()),
                        ("gcc", shutil.which("gcc")),
                        ("xtensa-esp32-elf-gcc", _xtensa())):
        if path:
            return label, path, False
    return None


def _stub_include_dir(platform: str) -> str | None:
    """A stub-HAL include tree so platform SDK headers (e.g. ESP-IDF
    <driver/i2c.h>) resolve when the native toolchain/SDK isn't installed.
    Declarations only — the judge compiles (-c), never links — giving real
    syntax and -Wall/-Wextra coverage for platform-idiomatic code."""
    plat = platform.lower()
    if "esp32" in plat or "xtensa" in plat:
        key = "esp32"
    elif "stm32" in plat:  # V1.7: CMSIS-style RCC/GPIO/I2C register definitions
        key = "stm32"
    else:
        return None
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stubs", key)
    return path if os.path.isdir(path) else None


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
    label, cc, exact = found
    if platform and not _recognized(platform):
        # Priority 3: an 'Other' platform we could not map to a toolchain. Say so
        # plainly instead of compiling with a possibly-mismatched compiler and
        # calling it validated — the label below shows what actually ran.
        report.notes.append(
            f"platform '{platform}' did not map to a known toolchain; compiled "
            f"with {label} for portable-C (-Wall -Wextra) coverage only — it may "
            "not match your target's compiler"
        )
    elif platform and not exact:
        # Recognized platform whose OWN toolchain isn't installed here (e.g.
        # esp32 with no xtensa gcc in the container). We fell back to a generic
        # C compiler — name BOTH the requested and the actual compiler (Fix 4)
        # so a fallback build is never read as a native-toolchain validation.
        want = requested_toolchain(platform) or "the target toolchain"
        report.notes.append(
            f"NOT TARGET-ACCURATE: platform '{platform}' requests {want}, which is "
            f"not available in this environment; compiled with {label} instead for "
            "portable-C (-Wall -Wextra) coverage only — it may not match your "
            "target's compiler"
        )

    sources = sorted(glob.glob(os.path.join(workdir, "*.c")))
    if not sources:
        report.checks["compile"] = "fail"
        report.failures.append(Failure("compile", workdir, None, "no .c sources to compile"))
        return

    includes = ["-I", workdir]
    stub_dir = _stub_include_dir(platform)
    if stub_dir:
        includes += ["-I", stub_dir]
        report.notes.append(f"stub HAL headers: {os.path.relpath(stub_dir)}")

    ok = True
    for src in sources:
        obj = src + ".o"
        cmd = [cc, *WARNING_FLAGS, "-c", src, *includes, "-o", obj]
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
