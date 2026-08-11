"""MCU reference-manual ingestion (V1.7, piece 3).

Produces an MCU peripheral map from a reference manual by:
  1. locating the RCC (clock), GPIO, and target-peripheral register sections via
     the PDF outline (rm_sections) — section-targeted, not whole-document;
  2. extracting registers each section two ways — table extraction for trusted
     OFFSETS, prose extraction for trusted BIT-FIELD names/positions — and
     merging them (merge_prose_fields);

This is the ingestion wiring; the formal cached-map SCHEMA is piece 4. The
device-datasheet pipeline (ingest_datasheet) is untouched — MCU ingestion is a
separate path so the ESP32/device flows cannot regress.
"""

from __future__ import annotations

import os
import re
import time

from ingestion.loader import load_document
from ingestion.prose import merge_prose_fields, scan_prose_registers
from ingestion.registers import (
    ExtractedRegister,
    classify_table,
    parse_bit_column_map,
    parse_headerless,
    parse_register_index,
)
from ingestion.rm_sections import find_section, read_outline
from ingestion.tables import stitch_tables

MCU_SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "schema", "mcu-map.schema.json",
)

# RCC clock-enable / peripheral-reset registers, e.g. RCC_APB1ENR, RCC_AHB1RSTR.
# LPENR (low-power) is excluded — the enable bit that matters is in *ENR.
RCC_ENR_RE = re.compile(r"RCC_?(A(?:HB|PB)\d)ENR$", re.IGNORECASE)
RCC_RSTR_RE = re.compile(r"RCC_?(A(?:HB|PB)\d)RSTR$", re.IGNORECASE)


def _table_registers(doc, pages: list[int]) -> list[ExtractedRegister]:
    """Register offsets from summary tables (reuses the device pipeline's table
    stages). Bit-field names from these tables are unreliable on RMs (reversed
    cell order) — prose overrides them in the merge."""
    out: list[ExtractedRegister] = []
    for t in stitch_tables(doc, pages=pages or None):
        kind = classify_table(t)
        if kind == "register_index":
            out.extend(parse_register_index(t))
        elif kind == "register_index_headerless":
            out.extend(parse_headerless(t))
        elif kind == "bit_column_map":
            out.extend(parse_bit_column_map(t))
    return out


def _dedupe_by_name(regs: list[ExtractedRegister]) -> list[ExtractedRegister]:
    """Same register can appear in more than one summary table; keep the first
    with a real offset, merge source pages."""
    by: dict[str, ExtractedRegister] = {}
    order: list[str] = []
    for r in regs:
        key = r.name.upper()
        if key not in by:
            by[key] = r
            order.append(key)
        else:
            keep = by[key]
            if not keep.offset and r.offset:
                keep.offset = r.offset
            for p in r.source_pages:
                if p not in keep.source_pages:
                    keep.source_pages.append(p)
    return [by[k] for k in order]


def extract_registers(pdf_path: str, page_range: tuple[int, int]) -> list[dict]:
    """Merged registers (table offsets + prose bit fields) for one page range."""
    lo, hi = page_range
    doc = load_document(pdf_path, page_range=page_range)
    pages = list(range(lo, hi + 1))
    table_regs = _dedupe_by_name(_table_registers(doc, pages))
    prose_regs = scan_prose_registers(doc, pages)
    merged = merge_prose_fields(table_regs, prose_regs)
    return [_reg_to_json(r) for r in merged]


def _reg_to_json(r: ExtractedRegister) -> dict:
    return {
        "name": r.name,
        "offset": r.offset or None,
        "reset_value": r.reset_value,
        "access": r.access,
        "fields": [
            {"name": f.name, "bits": f.bits, "description": f.description}
            for f in r.fields
        ],
        "confidence": r.confidence,
        "source_pages": sorted(set(r.source_pages)),
    }


def _range_for(sections, *patterns, variant=None):
    """First located (start, end) among the given title patterns, else None."""
    for pat in patterns:
        s = find_section(sections, pat, variant=variant)
        if s is not None and s.end_page is not None:
            return (s.start_page, s.end_page)
    return None


def _low_bit(bits: str) -> int | None:
    m = re.match(r"\[(\d+):(\d+)\]", bits)
    return int(m.group(2)) if m else None


def _derive_clock_controls(clock_registers: list[dict]) -> tuple[list, list]:
    """Item 4 payoff: turn RCC *ENR/*RSTR register bit fields into a directly
    cross-checkable table — peripheral -> bus -> register -> bit. 'I2C1EN' at
    bit 21 of RCC_APB1ENR becomes {peripheral: I2C1, bus: APB1, bit: 21}."""
    enables, resets = [], []
    for reg in clock_registers:
        name = reg["name"].replace(" ", "")
        me, mr = RCC_ENR_RE.search(name), RCC_RSTR_RE.search(name)
        if me:
            bus, suffix, sink = me.group(1).upper(), "EN", enables
        elif mr:
            bus, suffix, sink = mr.group(1).upper(), "RST", resets
        else:
            continue
        for f in reg.get("fields", []):
            fn = f["name"]
            if not fn.upper().endswith(suffix) or len(fn) <= len(suffix):
                continue
            bit = _low_bit(f["bits"])
            if bit is None:
                continue
            sink.append({
                "peripheral": fn[: -len(suffix)],
                "bus": bus,
                "register": reg["name"],
                "bit": bit,
                "confidence": reg.get("confidence", "medium"),
                "source_pages": reg.get("source_pages", []),
            })
    return enables, resets


def _rm_revision(pdf_path: str) -> str | None:
    """Best-effort RM revision from the cover ('RM0090 Rev 19'). null if absent —
    a wrong revision claimed confidently is worse than none (WS1 discipline)."""
    try:
        doc = load_document(pdf_path, page_range=(1, 2))
    except Exception:
        return None
    for page in doc.pages:
        m = re.search(r"(RM\d{3,5})\s*.*?\bRev(?:ision)?\.?\s*([0-9]+)",
                      page.text, re.IGNORECASE | re.DOTALL)
        if m:
            return f"{m.group(1).upper()} Rev {m.group(2)}"
    return None


def build_mcu_map(
    pdf_path: str, peripheral: str = "I2C", variant: str | None = None
) -> dict:
    """Schema-valid MCU map: section-targeted extraction + the derived
    clock-enable/reset tables + overall confidence. Validated against
    schema/mcu-map.schema.json before returning."""
    raw = ingest_mcu(pdf_path, peripheral=peripheral, variant=variant)
    enables, resets = _derive_clock_controls(raw["clock_registers"])

    have_clock = bool(enables)
    have_periph = bool(raw["peripheral_registers"])
    confidence = (
        "high" if have_clock and have_periph
        else "medium" if have_clock or have_periph
        else "low"
    )
    if not have_clock:
        raw["warnings"].append(
            f"no clock-enable bit derived for {peripheral} — clock cross-check "
            "will be unavailable"
        )

    mcu_map = {
        "mcu_family": raw["mcu_family"],
        "variant": variant,
        "reference_manual": raw["reference_manual"],
        "rm_revision": _rm_revision(pdf_path),
        "peripheral": peripheral,
        # tuples serialize to JSON arrays, but jsonschema validates the in-memory
        # object where a tuple is not an 'array' — store lists.
        "sections": {k: (list(v) if v else None) for k, v in raw["sections"].items()},
        "clock_enables": enables,
        "reset_controls": resets,
        "clock_registers": raw["clock_registers"],
        "gpio_registers": raw["gpio_registers"],
        "peripheral_registers": raw["peripheral_registers"],
        "extraction_confidence": confidence,
        "extraction_seconds": raw["extraction_seconds"],
        "warnings": raw["warnings"],
    }
    _validate_mcu_map(mcu_map)
    return mcu_map


def _validate_mcu_map(mcu_map: dict) -> None:
    import json

    import jsonschema

    with open(MCU_SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(mcu_map, schema)


def ingest_mcu(
    pdf_path: str, peripheral: str = "I2C", variant: str | None = None
) -> dict:
    """Section-targeted MCU ingest: clock (RCC) + GPIO + the peripheral's
    registers, each merged (table offsets + prose bit fields). Returns a
    structured result; the formal schema/caching is piece 4."""
    t0 = time.time()
    sections = read_outline(pdf_path)
    warnings: list[str] = []
    if not sections:
        warnings.append("no PDF outline — section targeting unavailable")

    clock_rng = _range_for(
        sections, r"RCC registers", r"Reset and clock", variant=variant
    )
    gpio_rng = _range_for(sections, r"GPIO registers", r"General-purpose I/?Os")
    periph_rng = _range_for(
        sections, rf"{peripheral} registers", rf"\b{peripheral}\b"
    )

    result: dict = {
        "mcu_family": "STM32F4",
        "variant": variant,
        "reference_manual": os.path.basename(pdf_path),
        "peripheral": peripheral,
        "sections": {"clock": clock_rng, "gpio": gpio_rng, "peripheral": periph_rng},
        "clock_registers": extract_registers(pdf_path, clock_rng) if clock_rng else [],
        "gpio_registers": extract_registers(pdf_path, gpio_rng) if gpio_rng else [],
        "peripheral_registers": (
            extract_registers(pdf_path, periph_rng) if periph_rng else []
        ),
        "warnings": warnings,
    }
    for key, rng in (("clock", clock_rng), ("gpio", gpio_rng),
                     ("peripheral", periph_rng)):
        if rng is None:
            warnings.append(f"could not locate the {key} section for {peripheral}")
    result["extraction_seconds"] = round(time.time() - t0, 1)
    return result
