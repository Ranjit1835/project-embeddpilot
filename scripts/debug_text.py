"""Spike aid: dump raw text of given pages."""

import sys

import pdfplumber


def main() -> None:
    path = sys.argv[1]
    pages = [int(p) for p in sys.argv[2].split(",")]
    with pdfplumber.open(path) as pdf:
        for pn in pages:
            print(f"=== page {pn} ===")
            print(pdf.pages[pn - 1].extract_text() or "(no text)")


if __name__ == "__main__":
    main()
