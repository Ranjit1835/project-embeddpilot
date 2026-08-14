"""V1.9 item 3: cross-check a fixed-readout driver against the extracted readout.

A register-less device (TMP125) has no register map to verify — with nothing
checked it would be grounded only by the compiler, precisely the ungrounded
generation this product exists to prevent. So the extracted readout parameters
(word width, value bit-slice, signedness, LSB weight) ARE the ground truth: the
generated code must declare them as named #defines, and each must match the
datasheet. A mismatch — or a missing parameter — is a HARD failure, exactly like
a wrong register offset. The judge greps the #defines rather than trying to
verify arbitrary shift/mask/scale expressions (the same discipline as the
register cross-check: verify the named constants, not every use).
"""

from __future__ import annotations

import re

from validator.report import Failure, ValidationReport

_DEFINE_RE = re.compile(r"^\s*#\s*define\s+(\w+)\s+(.+?)\s*(?:/\*.*)?$")


def _defines(files: dict[str, list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for lines in files.values():
        for line in lines:
            m = _DEFINE_RE.match(line)
            if m:
                out[m.group(1).upper()] = m.group(2).strip()
    return out


def _num(v: str) -> float | int | None:
    v = v.strip()
    v = re.sub(r"[fFuUlL]+$", "", v)
    try:
        return float(v) if ("." in v or "e" in v.lower()) else int(v, 0)
    except ValueError:
        return None


def readout_crosscheck(
    files: dict[str, list[str]], readout: dict, report: ValidationReport
) -> None:
    defs = _defines(files)

    def find(suffix: str):
        for k, v in defs.items():
            if k.endswith(suffix):
                return _num(v)
        return None

    checks = {
        "_WORD_BITS": ("word width", find("_WORD_BITS"), readout["bit_width"]),
        "_VALUE_MSB": ("value MSB", find("_VALUE_MSB"), readout["value_msb"]),
        "_VALUE_LSB": ("value LSB", find("_VALUE_LSB"), readout["value_lsb"]),
        "_SIGNED": ("signedness", find("_SIGNED"), 1 if readout["signed"] else 0),
        "_LSB_WEIGHT": ("LSB weight", find("_LSB_WEIGHT"), readout["lsb_weight"]),
    }

    missing = [label for _, (label, got, _) in
               [(k, v) for k, v in checks.items()] if got is None]
    if missing:
        report.checks["readout_crosscheck"] = "fail"
        report.failures.append(Failure(
            "readout_crosscheck", "", None,
            f"readout parameter #define(s) missing: {missing}. The driver's "
            "bit-slice / sign / scale cannot be grounded against the datasheet — "
            "refusing to validate an ungrounded readout driver."))
        return

    bad: list[str] = []
    for _suffix, (label, got, want) in checks.items():
        if _suffix == "_LSB_WEIGHT":
            ok = abs(float(got) - float(want)) < 1e-9
        else:
            ok = int(got) == int(want)
        if not ok:
            bad.append(f"{label}: code={got} vs datasheet={want}")

    if bad:
        report.checks["readout_crosscheck"] = "fail"
        for b in bad:
            report.failures.append(Failure(
                "readout_crosscheck", "", None, f"readout parameter mismatch — {b}"))
    else:
        report.checks["readout_crosscheck"] = "pass"
        report.notes.append(
            "readout parameters cross-checked against the datasheet: "
            f"{readout['bit_width']}-bit word, value "
            f"[{readout['value_msb']}:{readout['value_lsb']}], "
            f"{'signed' if readout['signed'] else 'unsigned'}, "
            f"{readout['lsb_weight']}/LSB")
