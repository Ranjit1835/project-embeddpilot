"""Section locator for MCU reference manuals (V1.7).

Reference manuals are huge (RM0090 = 1751 pages); whole-document extraction is
~6 minutes and wasteful. The PDF outline (bookmarks) maps every chapter to an
exact page in ~2s, so extraction can target only the chapters a peripheral
needs (RCC clock, GPIO, the peripheral itself).

Split for testability: `read_outline` touches the PDF and returns raw
(level, title, page) entries; `build_sections` / `find_section` /
`peripheral_pages` are pure and unit-tested. `read_outline` is smoke-checked
against a real RM in the pipeline tests.

Silicon-variant note: RM0090 carries parallel chapters per die family (e.g. two
RCC chapters — one for STM32F42xxx/43xxx, one for STM32F405/07/415/17). Callers
pass a `variant` substring to pin the right one, or extraction will conflate
register banks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Section:
    level: int
    title: str
    start_page: int
    end_page: int | None  # inclusive; None for the final section


def build_sections(
    entries: list[tuple[int, str, int | None]]
) -> list[Section]:
    """Turn ordered (level, title, page) outline entries into Sections with an
    end_page. A section ends just before the next entry whose level is <= its
    own (the next sibling-or-higher heading). Entries with an unresolved page
    (None) are skipped."""
    resolved = [(lvl, title, pg) for (lvl, title, pg) in entries if pg is not None]
    out: list[Section] = []
    for i, (lvl, title, pg) in enumerate(resolved):
        end: int | None = None
        for lvl2, _t2, pg2 in resolved[i + 1:]:
            if lvl2 <= lvl:
                end = max(pg, pg2 - 1)
                break
        out.append(Section(level=lvl, title=title.strip(), start_page=pg, end_page=end))
    return out


def find_section(
    sections: list[Section], pattern: str, variant: str | None = None
) -> Section | None:
    """First section whose title matches `pattern` (regex, case-insensitive).
    When `variant` is given and any match's title contains it, restrict to those
    — this pins the right one of several same-named chapters (the RCC split)."""
    rx = re.compile(pattern, re.IGNORECASE)
    matches = [s for s in sections if rx.search(s.title)]
    if not matches:
        return None
    if variant:
        vmatches = [s for s in matches if variant.lower() in s.title.lower()]
        if vmatches:
            return vmatches[0]
    return matches[0]


def peripheral_pages(
    sections: list[Section], peripheral: str
) -> tuple[int, int] | None:
    """(start, end) page range for a named peripheral's chapter, e.g. 'I2C'.
    Word-boundary matched so 'I2C' does not hit 'I2S'. Returns None if absent."""
    s = find_section(sections, rf"\b{re.escape(peripheral)}\b")
    if s is None or s.end_page is None:
        return None
    return (s.start_page, s.end_page)


def read_outline(pdf_path: str) -> list[Section]:
    """Read the PDF outline and resolve each bookmark to a page number, returning
    Sections. Requires the PDF to carry an outline (RM0090 does — 2201 entries)."""
    import pdfplumber
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdftypes import resolve1

    entries: list[tuple[int, str, int | None]] = []
    with pdfplumber.open(pdf_path) as pdf:
        doc = pdf.doc
        pageid_to_idx = {
            page.pageid: i
            for i, page in enumerate(PDFPage.create_pages(doc), start=1)
        }

        def dest_to_page(dest, action) -> int | None:
            try:
                d = dest
                if d is None and action:
                    a = resolve1(action)
                    if isinstance(a, dict):
                        d = a.get("D")
                d = resolve1(d)
                if isinstance(d, list) and d:
                    return pageid_to_idx.get(getattr(d[0], "objid", None))
            except Exception:
                pass
            return None

        try:
            outlines = list(doc.get_outlines())
        except Exception:
            return []
        for (level, title, dest, action, _se) in outlines:
            entries.append((level, (title or "").strip(), dest_to_page(dest, action)))
    return build_sections(entries)
