"""Stage 5: orchestrator. file -> canonical register map JSON (schema-valid).

The output of this module is the ONLY artifact the generation pipeline may
consume — never the raw PDF. That is the contamination-guard boundary for
Workstream 2.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from ingestion.loader import Document, load_document
from ingestion.registers import (
    ExtractedRegister,
    classify_table,
    parse_bit_column_map,
    parse_bit_fields,
    parse_headerless,
    parse_register_index,
)
from ingestion.sections import register_pages
from ingestion.tables import stitch_tables

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "schema", "register-map.schema.json",
)


def ingest_datasheet(
    path: str,
    peripheral: str = "",
    chip: str = "",
    max_pages: int | None = None,
    page_range: tuple[int, int] | None = None,
    progress=None,
) -> dict:
    """Run the full ingestion pipeline. Returns a dict matching
    schema/register-map.schema.json. Never raises on bad content —
    bad content becomes low confidence + warnings instead.

    `progress`, if given, is called with a stage name at each boundary:
    extracting_text -> extracting_tables -> building_map (UI stage feed)."""
    notify = progress or (lambda stage: None)
    notify("extracting_text")
    doc = load_document(path, max_pages=max_pages, page_range=page_range)
    warnings = list(doc.warnings)

    pages = register_pages(doc)
    if page_range and not pages:  # user pinned a range; trust it over the classifier
        lo, hi = page_range
        pages = list(range(lo, hi + 1))
        warnings.append(
            f"section classifier found no register pages in {lo}-{hi}; "
            "using the full requested range"
        )
    if not pages:
        warnings.append("no register-relevant pages detected")

    notify("extracting_tables")
    tables = stitch_tables(doc, pages=pages or None)
    notify("building_map")

    from ingestion.commands import ExtractedCommand, is_command_table, parse_command_table

    registers: list[ExtractedRegister] = []
    commands: list[ExtractedCommand] = []
    orphan_fields = []  # bit-field tables seen before any register claimed them
    for t in tables:
        # command tables first: opcode tables masquerade as register indexes
        # (WS1 finding 2 — W25Q64 opcodes were mislabeled as registers)
        if is_command_table(t):
            commands.extend(parse_command_table(t))
            continue
        kind = classify_table(t)
        if kind == "register_index":
            registers.extend(parse_register_index(t))
        elif kind == "register_index_headerless":
            registers.extend(parse_headerless(t))
        elif kind == "bit_column_map":
            registers.extend(parse_bit_column_map(t))
        elif kind == "bit_fields":
            fields = parse_bit_fields(t)
            # attach to the most recent register from the same/preceding page
            target = _nearest_register(registers, t.source_pages)
            if target is not None and not target.fields:
                target.fields.extend(fields)
            elif fields:
                orphan_fields.append((t.source_pages, len(fields)))

    # reference manuals put name+offset in text headings above bit diagrams;
    # this also cross-checks (and fills gaps in) the summary-table extraction
    from ingestion.textscan import scan_register_headings

    registers.extend(scan_register_headings(doc, pages=pages or None))

    registers, base_address = _merge_relative_absolute(_dedupe(registers), warnings)
    for pages_, n in orphan_fields:
        warnings.append(
            f"{n} bit-field rows on pages {pages_} could not be attached to a register"
        )

    commands = _dedupe_commands(commands)
    result = {
        "peripheral": peripheral,
        "chip": chip or os.path.splitext(os.path.basename(path))[0],
        # inferred memory-mapped base; null = bus-attached device (I2C/SPI),
        # which switches the WS2 worker to the transfer-callback contract
        "base_address": base_address,
        "registers": [_reg_to_json(r) for r in registers],
        "commands": [asdict(c) for c in commands],
        "extraction_confidence": _overall_confidence(registers, doc)
        if registers or not commands
        else "medium",
        "source_pages": sorted(
            {p for r in registers for p in r.source_pages}
            | {p for c in commands for p in c.source_pages}
        ),
        "warnings": warnings,
        "low_confidence_pages": sorted(
            set(doc.scanned_pages)
            | {p for r in registers if r.confidence == "low" for p in r.source_pages}
        ),
    }
    _validate(result)
    return result


def _dedupe_commands(commands):
    """Same name+opcode from summary + detail tables: keep the richer copy."""
    by_key = {}
    for c in commands:
        key = (c.name.upper(), c.opcode.upper())
        kept = by_key.get(key)
        if kept is None:
            by_key[key] = c
            continue
        kept.description = kept.description or c.description
        kept.address_bytes = kept.address_bytes if kept.address_bytes is not None else c.address_bytes
        kept.data_direction = kept.data_direction or c.data_direction
        kept.source_pages = sorted(set(kept.source_pages) | set(c.source_pages))
    return list(by_key.values())


def _nearest_register(
    registers: list[ExtractedRegister], field_pages: list[int]
) -> ExtractedRegister | None:
    if not registers or not field_pages:
        return None
    first_field_page = min(field_pages)
    candidates = [r for r in registers if min(r.source_pages, default=0) <= first_field_page]
    return candidates[-1] if candidates else None


def _dedupe(registers: list[ExtractedRegister]) -> list[ExtractedRegister]:
    """Same name+offset seen twice (summary table + description table):
    keep one, merge fields, prefer the copy that knows more. A placeholder
    (REG_0xF7) at an offset where a NAMED register exists is the same
    register seen by a parser that couldn't read the name column."""
    by_key: dict[tuple[str, str], ExtractedRegister] = {}
    for r in registers:
        key = (r.name.upper(), r.offset.upper())
        kept = by_key.get(key)
        if kept is None:
            by_key[key] = r
            continue
        _merge_into(kept, r)

    named_at: dict[str, ExtractedRegister] = {}
    for (name, offset), r in by_key.items():
        if not name.startswith("REG_0X"):
            named_at.setdefault(offset, r)
    out = []
    for (name, offset), r in by_key.items():
        if name.startswith("REG_0X") and offset in named_at:
            _merge_into(named_at[offset], r)
        else:
            out.append(r)
    return out


def _merge_into(kept: ExtractedRegister, r: ExtractedRegister) -> None:
    kept.reset_value = kept.reset_value or r.reset_value
    kept.access = kept.access or r.access
    if not kept.fields:
        kept.fields = r.fields
    kept.source_pages = sorted(set(kept.source_pages) | set(r.source_pages))
    order = {"high": 2, "medium": 1, "low": 0}
    if order[r.confidence] > order[kept.confidence]:
        kept.confidence = r.confidence


def _merge_relative_absolute(
    registers: list[ExtractedRegister], warnings: list[str]
) -> tuple[list[ExtractedRegister], str | None]:
    """Summary tables often list absolute mapped addresses (0x3FF53000) while
    description headings list peripheral-relative offsets (0x0000). Same name
    at one small and one large offset is the same register; keep the relative
    offset (what driver codegen needs) and merge the rest.

    Merged pairs also reveal the peripheral base address; registers seen ONLY
    at an absolute address (COMDn banks with no individual heading) get
    rebased with it."""
    from collections import Counter

    by_name: dict[str, list[ExtractedRegister]] = {}
    for r in registers:
        by_name.setdefault(r.name.upper(), []).append(r)
    out: list[ExtractedRegister] = []
    bases: Counter[int] = Counter()
    for group in by_name.values():
        if len(group) == 2:
            rel, abs_ = sorted(group, key=lambda r: int(r.offset, 16))
            if int(rel.offset, 16) < 0x10000 <= int(abs_.offset, 16):
                rel.reset_value = rel.reset_value or abs_.reset_value
                rel.access = rel.access or abs_.access
                if not rel.fields:
                    rel.fields = abs_.fields
                rel.source_pages = sorted(set(rel.source_pages) | set(abs_.source_pages))
                bases[int(abs_.offset, 16) - int(rel.offset, 16)] += 1
                out.append(rel)
                continue
        out.extend(group)

    base_address = None
    if bases:
        base, votes = bases.most_common(1)[0]
        base_address = f"0x{base:08X}"
        rebased = 0
        for r in out:
            addr = int(r.offset, 16)
            if addr >= 0x10000 and 0 <= addr - base < 0x10000:
                r.offset = f"0x{addr - base:04X}"
                r.parse_issues.append(f"rebased from 0x{addr:08X}")
                rebased += 1
        if rebased:
            warnings.append(
                f"rebased {rebased} absolute addresses using inferred base "
                f"{base_address} (confirmed by {votes} register(s) seen both ways)"
            )
    return out, base_address


def _overall_confidence(registers: list[ExtractedRegister], doc: Document) -> str:
    if not registers:
        return "low"
    if doc.scanned_pages:
        return "low"
    order = {"high": 2, "medium": 1, "low": 0}
    score = sum(order[r.confidence] for r in registers) / (2 * len(registers))
    if score >= 0.8:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _reg_to_json(r: ExtractedRegister) -> dict:
    d = asdict(r)
    d.pop("parse_issues", None)
    return d


def _validate(result: dict) -> None:
    import jsonschema

    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(result, schema)
