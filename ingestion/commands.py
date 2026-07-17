"""Command/instruction table extraction (V1.5 Amendment 2).

Command-based devices (SPI flash, and sensors driven by writing command
values into a control register) publish opcode tables, not register maps.
These parse into the canonical `commands` array — mislabeling opcodes as
registers was WS1 finding 2.

Two shapes are recognized:
  A. Instruction-set tables (W25Q64JV style): header has 'Byte 1'/'Instruction'
     /'Op code'; Byte 2+ columns encode address bytes (A23-A16), dummy bytes,
     and data direction (parenthesized cells = device output).
  B. Measurement-command tables (BMP180 style): a 'Control register value'
     column of hex command values, names carried on neighboring rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ingestion.registers import _norm_hex
from ingestion.tables import LogicalTable

OPCODE_HEADER_RE = re.compile(r"\b(instruction|op\s*code|opcode|command|byte\s*1)\b", re.IGNORECASE)
VALUE_HEADER_RE = re.compile(r"register\s+value", re.IGNORECASE)
MEASUREMENT_RE = re.compile(r"\bmeasurement\b", re.IGNORECASE)
ADDR_BYTE_RE = re.compile(r"^A\d+\s*-\s*A?\d+", re.IGNORECASE)
OUTPUT_CELL_RE = re.compile(r"^\(.+\)")          # (D7-D0), (MF7-MF0): device drives the bus
DATA_IN_RE = re.compile(r"^D\d+\s*-\s*D\d+")     # bare D7-D0: host writes data
SKIP_NAME_RE = re.compile(r"number of clock|data input output", re.IGNORECASE)


@dataclass
class ExtractedCommand:
    name: str
    opcode: str
    description: str = ""
    address_bytes: int | None = None
    dummy_cycles: int | None = None
    data_direction: str | None = None  # read | write | none | None
    source_pages: list[int] = field(default_factory=list)


def _header_candidates(t: LogicalTable) -> list[list[str]]:
    """Instruction-table headers ('Data Input Output | Byte 1 | ...') don't
    match the generic register-header hints, so stitching leaves them as body
    rows — treat the first rows as header candidates too."""
    return [t.header] + t.rows[:2]


def is_command_table(t: LogicalTable) -> bool:
    for row in _header_candidates(t):
        if OPCODE_HEADER_RE.search(" ".join(row)):
            return True
    # BMP180-style: 'Control register value' header + a Measurement label —
    # both often land in body rows because of merged cells
    all_text = " ".join(t.header) + " " + " ".join(c for r in t.rows for c in r)
    return bool(VALUE_HEADER_RE.search(all_text) and MEASUREMENT_RE.search(all_text))


def parse_command_table(t: LogicalTable) -> list[ExtractedCommand]:
    opcode_col = _opcode_column(t)
    if opcode_col is None:
        return []
    out: list[ExtractedCommand] = []
    carried_name = ""  # names and values can land on adjacent rows (merged cells)
    for row in t.rows:
        name = next(
            (c.strip() for i, c in enumerate(row)
             if i != opcode_col and c.strip() and re.search(r"[A-Za-z]{2,}", c)
             and _norm_hex(c) is None),
            "",
        )
        if name and not SKIP_NAME_RE.search(name):
            carried_name = name
        opcode = _norm_hex(row[opcode_col]) if opcode_col < len(row) else None
        if opcode is None or not carried_name or SKIP_NAME_RE.search(carried_name):
            continue

        rest = [c.strip() for i, c in enumerate(row) if i > opcode_col and c.strip()]
        addr = sum(1 for c in rest if ADDR_BYTE_RE.match(c)) or None
        dummies = sum(1 for c in rest if c.lower().startswith("dummy"))
        outputs = any(OUTPUT_CELL_RE.match(c) for c in rest)
        writes = any(DATA_IN_RE.match(c) for c in rest)
        if rest or len(t.header) > 3:  # instruction-set style rows carry direction info
            direction = "read" if outputs else "write" if writes else "none"
        else:
            direction = None  # value-table style says nothing about direction

        out.append(
            ExtractedCommand(
                name=carried_name,
                opcode=opcode,
                description=_describe(rest),
                address_bytes=addr,
                # dummy BYTES are visible in the table; CYCLES depend on bus
                # width per mode — never guess, record bytes in description
                dummy_cycles=None,
                data_direction=direction,
                source_pages=list(t.source_pages),
            )
        )
        carried_name = ""  # a name pairs with exactly one opcode row
    return out


def _opcode_column(t: LogicalTable) -> int | None:
    for row in _header_candidates(t):
        for i, h in enumerate(row):
            if OPCODE_HEADER_RE.search(h):
                return i
    # data-driven: leftmost column whose non-empty cells are mostly strict hex
    ncols = max((len(r) for r in t.rows), default=0)
    for i in range(ncols):
        cells = [r[i].strip() for r in t.rows if i < len(r) and r[i].strip()]
        if len(cells) >= 3 and sum(1 for c in cells if _norm_hex(c)) / len(cells) >= 0.6:
            return i
    return None


def _describe(rest: list[str]) -> str:
    dummies = sum(1 for c in rest if c.lower().startswith("dummy"))
    parts = []
    if dummies:
        parts.append(f"{dummies} dummy byte(s)")
    seq = ", ".join(c for c in rest if not c.lower().startswith("dummy"))
    if seq:
        parts.append(f"sequence: {seq}")
    return "; ".join(parts)
