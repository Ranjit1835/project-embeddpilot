"""Text-pattern extraction for reference manuals whose register descriptions
are headings + bit-diagram graphics rather than parseable tables.

Espressif-style TRMs print 'Register 21.3. I2C_SR_REG (0x0008)' above each
diagram; the diagram's rotated field text arrives scrambled from the PDF text
layer, so field bit positions are NOT recoverable here — register name/offset
are, and they cross-check the summary table.
"""

from __future__ import annotations

import re

from ingestion.loader import Document
from ingestion.registers import ExtractedRegister

REG_HEADING_RE = re.compile(
    r"Register\s*\d+\.\d+\.?\s*([A-Z][A-Z0-9_]{2,})\s*\(\s*0[xX]([0-9A-Fa-f]+)\s*\)"
)


def scan_register_headings(
    doc: Document, pages: list[int] | None = None
) -> list[ExtractedRegister]:
    wanted = set(pages) if pages is not None else None
    out: list[ExtractedRegister] = []
    for page in doc.pages:
        if wanted is not None and page.number not in wanted:
            continue
        for m in REG_HEADING_RE.finditer(page.text):
            out.append(
                ExtractedRegister(
                    name=m.group(1),
                    offset="0x" + m.group(2).upper(),
                    confidence="high",
                    source_pages=[page.number],
                    parse_issues=["from register description heading"],
                )
            )
    return out
