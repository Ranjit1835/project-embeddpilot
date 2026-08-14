"""CLI entry: python -m validator <workdir> --map <register-map.json>
[--platform esp32] [--out report.json]

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
from validator.static_check import static_check

EXIT_CODES = {"validated": 0, "validated-with-unverified-fields": 1, "failed": 2}


def main() -> int:
    ap = argparse.ArgumentParser(prog="validator")
    ap.add_argument("workdir")
    ap.add_argument("--map", required=True, help="register map JSON path")
    ap.add_argument("--mcu-map", help="MCU map JSON path (V1.7 clock/GPIO cross-check)")
    ap.add_argument("--platform", default="portable")
    ap.add_argument("--target", default="bare-metal",
                    choices=["bare-metal", "arduino"],
                    help="output target: bare-metal C driver or Arduino library")
    ap.add_argument("--out")
    args = ap.parse_args()

    with open(args.map, encoding="utf-8") as f:
        register_map = json.load(f)
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
        crosscheck(files, register_map, report, mcu_map)
        if mcu_map is not None:
            from validator.mcu_crosscheck import mcu_crosscheck
            mcu_crosscheck(files, mcu_map, report)
        scan_unverified_computations(files, report)
        if args.target == "arduino":
            # items 4-6 (clock/GPIO/init) belong to the Arduino core, not us —
            # no MCU compile; instead prove board-agnosticism across real cores.
            arduino_compile_check(args.workdir, report)
        else:
            compile_check(args.workdir, args.platform, report)
            static_check(args.workdir, report)
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
