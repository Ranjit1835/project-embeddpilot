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

from validator.compile_check import compile_check
from validator.crosscheck import crosscheck, scan_unverified_computations
from validator.report import ValidationReport
from validator.static_check import static_check

EXIT_CODES = {"validated": 0, "validated-with-unverified-fields": 1, "failed": 2}


def main() -> int:
    ap = argparse.ArgumentParser(prog="validator")
    ap.add_argument("workdir")
    ap.add_argument("--map", required=True, help="register map JSON path")
    ap.add_argument("--platform", default="portable")
    ap.add_argument("--out")
    args = ap.parse_args()

    with open(args.map, encoding="utf-8") as f:
        register_map = json.load(f)

    files: dict[str, list[str]] = {}
    for path in sorted(
        glob.glob(os.path.join(args.workdir, "*.c"))
        + glob.glob(os.path.join(args.workdir, "*.h"))
    ):
        with open(path, encoding="utf-8", errors="replace") as f:
            files[os.path.basename(path)] = f.read().splitlines()

    report = ValidationReport()
    if not files:
        report.checks["register_crosscheck"] = "skipped"
        report.checks["compile"] = "skipped"
        report.notes.append("no generated sources found")
    else:
        crosscheck(files, register_map, report)
        scan_unverified_computations(files, report)
        compile_check(args.workdir, args.platform, report)
        static_check(args.workdir, report)
    report.finalize()

    text = json.dumps(report.to_json(), indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return EXIT_CODES[report.status]


if __name__ == "__main__":
    sys.exit(main())
