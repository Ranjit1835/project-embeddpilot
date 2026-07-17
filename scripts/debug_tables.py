"""Spike debugging aid: dump raw pdfplumber tables for given pages."""

import sys

import pdfplumber


def main() -> None:
    path = sys.argv[1]
    pages = [int(p) for p in sys.argv[2].split(",")]
    with pdfplumber.open(path) as pdf:
        for pn in pages:
            page = pdf.pages[pn - 1]
            tables = page.extract_tables() or []
            print(f"=== page {pn}: {len(tables)} table(s) ===")
            for i, t in enumerate(tables):
                print(f"--- table {i} ---")
                for row in t[:14]:
                    print([("" if c is None else " ".join(str(c).split()))[:30] for c in row])


if __name__ == "__main__":
    main()
