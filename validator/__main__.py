"""CLI entry: python -m validator <workdir> --map <register-map.json>
[--platform esp32] [--devices <devices.json>] [--out report.json]

Prints the validation report JSON to stdout (or --out). Exit codes:
0 = validated, 1 = validated-with-unverified-fields, 2 = failed.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from validator.arduino_check import arduino_compile_check
from validator.compile_check import compile_check
from validator.crosscheck import crosscheck, scan_unverified_computations
from validator.report import ValidationReport
from validator.resource_crosscheck import resource_crosscheck
from validator.static_check import static_check

EXIT_CODES = {"validated": 0, "validated-with-unverified-fields": 1, "failed": 2}


def _load_devices(path: str, fail) -> list[dict]:
    """Read the --devices payload into the composed-device list the resource
    cross-check consumes (structure documented in validator/resource_crosscheck).

    Accepts a bare JSON list or an object with a "devices" list. Anything else
    is a caller error and stops the run: the user explicitly asked for a
    composition check, so degrading to "nothing to compose" would report
    not_applicable for a check that was requested — the same silent-skip the
    check's own three states exist to prevent."""
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, dict):
        payload = payload.get("devices")
    if not isinstance(payload, list) or any(
        not isinstance(d, dict) for d in payload
    ):
        fail(f"--devices {path}: expected a JSON list of composed-device objects, "
             'or an object with a "devices" list')
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(prog="validator")
    ap.add_argument("workdir")
    ap.add_argument("--map", required=True, help="register map JSON path")
    ap.add_argument("--mcu-map", help="MCU map JSON path (V1.7 clock/GPIO cross-check)")
    ap.add_argument("--platform", default="portable")
    ap.add_argument("--target", default="bare-metal",
                    choices=["bare-metal", "arduino"],
                    help="output target: bare-metal C driver or Arduino library")
    ap.add_argument("--devices",
                    help="composed-system device list JSON (V2 resource "
                         "cross-check). Omitted = single-device run: the "
                         "resource check reports not_applicable")
    ap.add_argument("--out")
    args = ap.parse_args()

    with open(args.map, encoding="utf-8") as f:
        register_map = json.load(f)
    # None (no --devices) and [] are both "nothing to compose" to the check,
    # which reports not_applicable for either — never a pass, never a skip.
    devices = _load_devices(args.devices, ap.error) if args.devices else None
    mcu_map = None
    if args.mcu_map and args.target != "arduino":
        with open(args.mcu_map, encoding="utf-8") as f:
            mcu_map = json.load(f)

    # The Arduino library is a nested folder of .cpp/.h/.ino; the bare-metal
    # driver is flat .c/.h. Both are loaded for the register/bit cross-check,
    # which is source-extension-agnostic (it scans #define lines).
    if args.target == "arduino":
        patterns = ("**/*.cpp", "**/*.h", "**/*.ino")
    else:
        patterns = ("*.c", "*.h")
    paths: list[str] = []
    for pat in patterns:
        paths += glob.glob(os.path.join(args.workdir, pat), recursive=True)

    files: dict[str, list[str]] = {}
    for path in sorted(set(paths)):
        with open(path, encoding="utf-8", errors="replace") as f:
            files[os.path.relpath(path, args.workdir)] = f.read().splitlines()

    report = ValidationReport()
    if not files:
        report.checks["register_crosscheck"] = "skipped"
        report.checks["compile"] = "skipped"
        report.notes.append("no generated sources found")
    else:
        readout = register_map.get("readout")
        if readout:
            # V1.9 item 3: fixed-readout device — no register map to check; the
            # readout parameters are the ground truth instead.
            from validator.readout_crosscheck import readout_crosscheck
            readout_crosscheck(files, readout, report)
        else:
            crosscheck(files, register_map, report, mcu_map)
            if mcu_map is not None:
                from validator.mcu_crosscheck import mcu_crosscheck
                mcu_crosscheck(files, mcu_map, report)
        scan_unverified_computations(files, report)
        # V1.10a: execute the generated conversion/compensation math against a
        # document-sourced oracle when one is present (bare-metal C target). No
        # oracle -> not_applicable (the UNVERIFIED marking stands, unchanged).
        from validator.math_crosscheck import math_crosscheck
        math_crosscheck(files, register_map, report)
        if args.target == "arduino":
            # items 4-6 (clock/GPIO/init) belong to the Arduino core, not us —
            # no MCU compile; instead prove board-agnosticism across real cores.
            arduino_compile_check(args.workdir, report)
        else:
            compile_check(args.workdir, args.platform, report)
            static_check(args.workdir, report)

    # V2 workstream 3: the SYSTEM-level cross-check. Every check above verifies
    # one device against one document; only this one can see two individually
    # correct drivers double-booking a pin, an address, a DMA stream or an IRQ.
    # It needs no toolchain and no generated sources, so it runs unconditionally
    # — outside the `files` branch — and always records one of its three states.
    # A conflict appends Failures, which finalize() turns into a hard failure.
    resource_crosscheck(devices, mcu_map, report)

    report.finalize()

    # V1.8 Part D: attach the 7-item scope-honesty panel (reads report + target).
    from validator.scope import build_scope
    report.scope = build_scope(args.target, register_map, report, mcu_map is not None)

    text = json.dumps(report.to_json(), indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return EXIT_CODES[report.status]


if __name__ == "__main__":
    sys.exit(main())
