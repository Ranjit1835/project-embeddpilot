"""Spike aid: find pages whose text matches a pattern. Usage:
python scripts/find_pages.py <pdf> <regex> [start] [end]
"""

import re
import sys

import pdfplumber


def main() -> None:
    path, pattern = sys.argv[1], sys.argv[2]
    start = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    end = int(sys.argv[4]) if len(sys.argv) > 4 else None
    rx = re.compile(pattern, re.IGNORECASE)
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages[start - 1 : end]
        for p in pages:
            text = p.extract_text() or ""
            hits = rx.findall(text)
            if hits:
                first_line = next(
                    (ln.strip() for ln in text.splitlines() if ln.strip()), ""
                )
                print(f"p{p.page_number}: {len(hits)} hit(s) | {first_line[:70]}")
            p.flush_cache()


if __name__ == "__main__":
    main()
