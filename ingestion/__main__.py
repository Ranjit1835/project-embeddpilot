"""CLI: python -m ingestion <datasheet.pdf|.docx> [options]

Examples:
  python -m ingestion extraction/input/bmp180.pdf --chip BMP180 --peripheral pressure-sensor
  python -m ingestion big_trm.pdf --pages 300-360 --out artifacts/map.json
"""

import argparse
import json
import sys

from ingestion.pipeline import ingest_datasheet


def main() -> int:
    ap = argparse.ArgumentParser(prog="ingestion")
    ap.add_argument("file")
    ap.add_argument("--chip", default="")
    ap.add_argument("--peripheral", default="")
    ap.add_argument("--pages", help="restrict to page range, e.g. 300-360")
    ap.add_argument("--max-pages", type=int, help="only read first N pages")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    args = ap.parse_args()

    page_range = None
    if args.pages:
        lo, _, hi = args.pages.partition("-")
        page_range = (int(lo), int(hi or lo))

    result = ingest_datasheet(
        args.file,
        peripheral=args.peripheral,
        chip=args.chip,
        max_pages=args.max_pages,
        page_range=page_range,
    )

    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        n = len(result["registers"])
        print(
            f"{n} registers -> {args.out} "
            f"(confidence: {result['extraction_confidence']})"
        )
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
