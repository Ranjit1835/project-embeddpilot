"""Stage 3: turn raw per-page tables into stitched logical tables.

Handles the three table pathologies the spec calls out:
  - multi-page tables: a table continuing on the next page, with or without
    its header row repeated
  - repeated headers: dropped when stitching
  - merged cells: pdfplumber emits None/"" for merged spans; rows are
    forward-filled from the previous row for the leading (identity) columns
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ingestion.loader import Document

HEADER_HINTS = re.compile(
    r"\b(register|name|mnemonic|symbol|addr|address|offset|reset|default|por|"
    r"access|type|r/w|attribute|bit|bits|field|description|function)\b",
    re.IGNORECASE,
)


@dataclass
class LogicalTable:
    header: list[str]
    rows: list[list[str]] = field(default_factory=list)
    source_pages: list[int] = field(default_factory=list)

    @property
    def signature(self) -> tuple[int, tuple[str, ...]]:
        return (len(self.header), tuple(h.lower().strip() for h in self.header))


def _looks_like_header(row: list[str]) -> bool:
    cells = [c for c in row if c]
    if len(cells) < 2:
        return False
    hits = sum(1 for c in cells if HEADER_HINTS.search(c))
    # header cells are short labels, not sentences
    short = sum(1 for c in cells if len(c) <= 40)
    return hits >= 2 and short >= len(cells) - 1


def forward_fill_columns(rows: list[list[str]], cols: list[int]) -> list[list[str]]:
    """Merged identity cells (register name/address spanning several field rows)
    arrive as empty strings; carry the value down — but ONLY for the given
    identity columns. Filling every column smears bit-field labels across
    unrelated registers (observed on BMP180 page 18)."""
    filled: list[list[str]] = []
    for row in rows:
        row = list(row)
        if filled:
            prev = filled[-1]
            for i in cols:
                if i < len(row) and i < len(prev) and not row[i].strip():
                    row[i] = prev[i]
        filled.append(row)
    return filled


def stitch_tables(doc: Document, pages: list[int] | None = None) -> list[LogicalTable]:
    """Walk pages in order; a headerless table whose column count matches the
    previous logical table is treated as its continuation."""
    wanted = set(pages) if pages is not None else None
    logical: list[LogicalTable] = []
    current: LogicalTable | None = None

    for page in doc.pages:
        if wanted is not None and page.number not in wanted:
            current = None  # a gap in relevant pages breaks continuation
            continue
        for raw in page.tables:
            rows = [r for r in raw if any(c.strip() for c in r)]
            if not rows:
                continue
            has_header = _looks_like_header(rows[0])
            body = rows[1:] if has_header else rows

            if has_header:
                header = rows[0]
                if current is not None and current.signature == (
                    len(header),
                    tuple(h.lower().strip() for h in header),
                ):
                    # same header repeated on a new page: continuation
                    current.rows.extend(body)
                    current.source_pages.append(page.number)
                else:
                    current = LogicalTable(
                        header=header, rows=list(body), source_pages=[page.number]
                    )
                    logical.append(current)
            elif current is not None and rows and len(rows[0]) == len(current.header):
                # headerless continuation with matching column count
                current.rows.extend(body)
                current.source_pages.append(page.number)
            else:
                # orphan table with no recognizable header; keep it,
                # registers.py may still salvage it by cell patterns
                current = LogicalTable(
                    header=[""] * len(rows[0]), rows=rows, source_pages=[page.number]
                )
                logical.append(current)

    for t in logical:
        t.source_pages = sorted(set(t.source_pages))
    return logical
