"""Prose bit-field extraction for MCU reference manuals (V1.7).

Reference manuals (STM32 RM0090 etc.) describe each register as a section:

    6.3.13 RCC APB1 peripheral clock enable register (RCC_APB1ENR)
    Address offset: 0x40
    Reset value: 0x0000 0000
      <bit diagram graphic — arrives scrambled from the text layer>
    Bit 21 I2C1EN: I2C1 clock enable
      0: I2C1 clock disabled
      1: I2C1 clock enabled
    Bits 15:8 FREQ[5:0]: Peripheral clock frequency
    ...

The V1.7 spike found that the bit-DIAGRAM summary tables reverse cell order in
the PDF text layer (I2C_SR1 -> 'devreseR/FPOTS/FTB' = Reserved/STOPF/BTF
reversed), so table-derived bit-field NAMES are unusable. The per-bit PROSE
("Bit 21 I2C1EN: ...") is clean and unambiguous, and is the reliable source for
bit fields with exact positions. This module parses that prose.

Register offsets still come from summary tables (registers.py); this module adds
the bit fields those tables mangle, plus register offset/reset from the section's
own 'Address offset:' / 'Reset value:' lines.
"""

from __future__ import annotations

import re

from ingestion.loader import Document
from ingestion.registers import ExtractedField, ExtractedRegister, _parse_field_label

# A register section heading: '... register (MNEMONIC)' or 'register 1 (I2C_CR1)'.
# The mnemonic is an all-caps identifier in parentheses at the heading's end.
REG_HEADING_RE = re.compile(
    r"\bregister\s*\d*\s*\(\s*([A-Z][A-Z0-9_]{2,})\s*\)", re.IGNORECASE
)
ADDR_OFFSET_RE = re.compile(r"Address\s+offset:\s*0x([0-9A-Fa-f]+)", re.IGNORECASE)
RESET_VALUE_RE = re.compile(
    r"Reset\s+value:\s*0x([0-9A-Fa-f](?:[0-9A-Fa-f ]*[0-9A-Fa-f])?)", re.IGNORECASE
)

# 'Bit 21 I2C1EN: ...'  or  'Bits 15:8 FREQ[5:0]: ...'
# group1 = high bit, group2 = low bit (optional), group3 = field label
# (may carry an embedded range), group4 = description.
BIT_LINE_RE = re.compile(
    r"^\s*Bits?\s+(\d+)\s*(?::\s*(\d+))?\s+"
    r"([A-Za-z][A-Za-z0-9_]*(?:\[\s*\d+\s*:\s*\d+\s*\])?)\s*:\s*(.*)$"
)

# Words that look like an identifier but are NOT a field name.
_NON_FIELDS = {"reserved", "res"}


def parse_bit_line(line: str) -> ExtractedField | None:
    """'Bit 21 I2C1EN: I2C1 clock enable' -> ExtractedField('I2C1EN', '[21:21]',
    'I2C1 clock enable'). Returns None for reserved/unparseable lines.

    The bit positions come from the 'Bit(s) N[:M]' prefix (authoritative — these
    are absolute positions in the register). Any range embedded in the field
    label (FREQ[5:0]) is stripped from the name; the label's width is only a
    sanity signal, not the position."""
    m = BIT_LINE_RE.match(line)
    if m is None:
        return None
    hi = int(m.group(1))
    lo = int(m.group(2)) if m.group(2) is not None else hi
    if lo > hi:
        hi, lo = lo, hi
    label = m.group(3).strip()
    name, _width = _parse_field_label(label)  # strips an embedded <x:y>/[x:y]
    if not name or name.lower() in _NON_FIELDS:
        return None
    return ExtractedField(
        name=name, bits=f"[{hi}:{lo}]", description=m.group(4).strip()
    )


def parse_bit_fields_prose(lines: list[str]) -> list[ExtractedField]:
    """Every bit-definition line in a block, in document order. Non-bit lines
    (bit-value enumerations '0: ... / 1: ...', notes, diagram debris) are
    ignored. Later duplicates of the same bit position lose to the first seen
    (the detailed section wins over any stray restatement)."""
    out: list[ExtractedField] = []
    seen: set[str] = set()
    for line in lines:
        f = parse_bit_line(line)
        if f is None or f.bits in seen:
            continue
        seen.add(f.bits)
        out.append(f)
    return out


def _norm_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()


def _names_match(a: str, b: str) -> bool:
    """Table and prose often disagree on the prefix: a summary table lists
    'APB1ENR' while the register section titles it 'RCC_APB1ENR'. Treat them as
    the same register when the shorter normalized name is a suffix of the longer
    (both >= 4 chars) or they are equal."""
    na, nb = _norm_name(a), _norm_name(b)
    if na == nb:
        return True
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(short) >= 4 and long.endswith(short)


def merge_prose_fields(
    table_regs: list[ExtractedRegister], prose_regs: list[ExtractedRegister]
) -> list[ExtractedRegister]:
    """Combine table extraction (trusted OFFSETS) with prose extraction (trusted
    BIT-FIELD names/positions). For registers found both ways, keep the table
    offset and replace its bit fields with the prose fields — the prose names are
    clean, the table's bit-diagram names are reversed. Prose-only registers are
    appended (the section prose is authoritative for the RM); table-only
    registers are kept as-is.

    Returns registers in table order, then any prose-only ones."""
    used_prose: set[int] = set()
    out: list[ExtractedRegister] = []
    for tr in table_regs:
        match = None
        for i, pr in enumerate(prose_regs):
            if i in used_prose:
                continue
            if _names_match(tr.name, pr.name):
                match = (i, pr)
                break
        if match is None:
            out.append(tr)
            continue
        i, pr = match
        used_prose.add(i)
        # the prose name comes from the register-section heading ('RCC_APB1ENR')
        # and is cleaner than table cells ('RCC_ APB1ENR'); it is also the
        # identifier generated code will be cross-checked against.
        tr.name = pr.name
        if pr.fields:  # prose bit-field names win over reversed table names
            tr.fields = pr.fields
        if not tr.offset and pr.offset:
            tr.offset = pr.offset
        if tr.reset_value is None:
            tr.reset_value = pr.reset_value
        for p in pr.source_pages:
            if p not in tr.source_pages:
                tr.source_pages.append(p)
        tr.confidence = "high" if (tr.offset and tr.fields) else tr.confidence
        tr.parse_issues.append("bit fields from register-section prose")
        out.append(tr)

    for i, pr in enumerate(prose_regs):
        if i not in used_prose:
            out.append(pr)
    return out


def scan_prose_registers(
    doc: Document, pages: list[int] | None = None
) -> list[ExtractedRegister]:
    """Walk the document, pairing each register-section heading with the prose
    bit fields that follow it (until the next heading). Offset and reset value
    come from the section's own 'Address offset:' / 'Reset value:' lines when
    present. Fields carry exact bit positions — the payoff over the reversed
    bit-diagram tables.

    `pages` restricts which pages are read (section-targeting); None reads all.
    A register's `source_pages` spans every page its heading and bit lines
    touched, so provenance survives sections that cross a page boundary."""
    wanted = set(pages) if pages is not None else None

    registers: list[ExtractedRegister] = []
    current: ExtractedRegister | None = None
    pending_lines: list[str] = []  # bit lines gathered for `current`

    def flush() -> None:
        nonlocal current
        if current is not None:
            current.fields = parse_bit_fields_prose(pending_lines)
            current.confidence = "high" if current.fields else "medium"
            if not current.fields:
                current.parse_issues.append("no bit-field prose found in section")
            registers.append(current)
        pending_lines.clear()

    for page in doc.pages:
        if wanted is not None and page.number not in wanted:
            continue
        for raw in page.text.splitlines():
            heading = REG_HEADING_RE.search(raw)
            if heading:
                flush()
                current = ExtractedRegister(
                    name=heading.group(1),
                    offset="",  # filled from 'Address offset:' below
                    confidence="medium",
                    source_pages=[page.number],
                    parse_issues=["from reference-manual register section"],
                )
                continue
            if current is None:
                continue
            if page.number not in current.source_pages:
                current.source_pages.append(page.number)
            if not current.offset:
                mo = ADDR_OFFSET_RE.search(raw)
                if mo:
                    current.offset = "0x" + mo.group(1).upper()
            if current.reset_value is None:
                mr = RESET_VALUE_RE.search(raw)
                if mr:
                    current.reset_value = "0x" + mr.group(1).replace(" ", "").upper()
            pending_lines.append(raw)
    flush()

    # A heading with no recoverable offset is still useful (fields cross-check by
    # name), but drop sections that yielded neither an offset nor any field —
    # those are false heading hits, not registers.
    return [r for r in registers if r.offset or r.fields]
