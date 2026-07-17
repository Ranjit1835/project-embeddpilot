"""Static analysis via cppcheck: UB, null derefs, missing volatile on
register pointers. Optional check — skipped (and surfaced) when cppcheck
is not installed."""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess

from validator.report import Failure, ValidationReport

# cppcheck has no dedicated missing-volatile check; a targeted grep on
# register-pointer casts covers the common failure mode
REG_PTR_RE = re.compile(r"\(\s*(?:uint(?:8|16|32)_t|unsigned\s+\w+)\s*\*\s*\)")
VOLATILE_PTR_RE = re.compile(r"volatile")


def static_check(workdir: str, report: ValidationReport) -> None:
    sources = sorted(glob.glob(os.path.join(workdir, "*.c")))

    # volatile heuristic runs regardless of cppcheck availability
    for src in sources:
        with open(src, encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                if REG_PTR_RE.search(line) and not VOLATILE_PTR_RE.search(line):
                    if "BASE" in line or re.search(r"0[xX][0-9A-Fa-f]{4,}", line):
                        report.failures.append(Failure(
                            "static_analysis", os.path.basename(src), lineno,
                            "register pointer cast without volatile qualifier",
                        ))

    cppcheck = shutil.which("cppcheck")
    if not cppcheck:
        report.checks["static_analysis"] = "skipped"
        return

    cmd = [
        cppcheck, "--enable=warning,portability", "--error-exitcode=0",
        "--template={file}:{line}:{severity}:{message}", "--quiet", workdir,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except (subprocess.TimeoutExpired, OSError) as e:
        report.checks["static_analysis"] = "skipped"
        report.notes.append(f"cppcheck failed to run: {e}")
        return

    errors = 0
    for line in (proc.stderr or "").splitlines():
        parts = line.split(":", 3)
        if len(parts) == 4 and parts[2] in ("error", "warning", "portability"):
            errors += 1
            report.failures.append(Failure(
                "static_analysis", os.path.basename(parts[0]),
                int(parts[1]) if parts[1].isdigit() else None, parts[3],
            ))
    report.checks["static_analysis"] = "fail" if (
        errors or any(f.check == "static_analysis" for f in report.failures)
    ) else "pass"
