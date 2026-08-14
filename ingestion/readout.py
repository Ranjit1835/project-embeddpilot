"""V1.9 item 3: fixed-readout device extraction.

Some minimal sensors have no register map at all — you clock out a fixed-format
data word and slice the value out of it (TMP125: a 16-bit SPI word whose bits
D14..D5 are a signed two's-complement temperature, 0.25 C/LSB). For these, the
register set is the wrong abstraction; the readout PARAMETERS are the ground
truth the generator must be held to.

This module extracts {bit_width, value_msb, value_lsb, signed, lsb_weight, unit}
from two corroborating sources — a bit-position table (D15..D0 over T9..T0) and a
value->code table — plus prose. Per the required grounding rule, if the
parameters cannot be determined with confidence it returns None: the caller must
BLOCK rather than fall back to ungrounded generation.
"""

from __future__ import annotations

import re

from ingestion.loader import Document
from ingestion.tables import LogicalTable, stitch_tables

_D_RE = re.compile(r"^D(\d+)$", re.IGNORECASE)
_T_RE = re.compile(r"^T(\d+)$", re.IGNORECASE)
_BIN_RE = re.compile(r"^[01]{4,}$")


def _find_bit_position_table(tabs: list[LogicalTable]) -> dict | None:
    """A table pairing data-word bits (D15..D0) with value-bit labels (T9..T0).
    Returns {bit_width, value_msb, value_lsb, pages}."""
    for t in tabs:
        rows = t.rows
        d_to_t: dict[int, int] = {}   # data-word bit -> value-bit index
        all_d: set[int] = set()
        for i in range(len(rows) - 1):
            drow, trow = rows[i], rows[i + 1]
            dcells = {j: int(m.group(1)) for j, c in enumerate(drow)
                      if (m := _D_RE.match(c.strip()))}
            if len(dcells) < 4:
                continue
            all_d |= set(dcells.values())
            for j, dbit in dcells.items():
                tl = trow[j].strip() if j < len(trow) else ""
                mt = _T_RE.match(tl)
                if mt:
                    d_to_t[dbit] = int(mt.group(1))
        if len(d_to_t) >= 4 and all_d:
            bit_width = max(all_d) + 1
            tmax = max(d_to_t.values())
            tmin = min(d_to_t.values())
            value_msb = max(d for d, tn in d_to_t.items() if tn == tmax)
            value_lsb = max(d for d, tn in d_to_t.items() if tn == tmin)
            return {"bit_width": bit_width, "value_msb": value_msb,
                    "value_lsb": value_lsb, "pages": list(t.source_pages)}
    return None


def _parse_value(cell: str) -> float | None:
    c = cell.strip().replace("+", "").replace("°C", "").replace("°", "").replace("C", "")
    c = c.replace("−", "-").strip()  # unicode minus
    try:
        return float(c)
    except ValueError:
        return None


def _find_value_code_table(tabs: list[LogicalTable]) -> dict | None:
    """A value->digital-code table: derive lsb_weight from two positive rows and
    signedness from the presence of negative values."""
    for t in tabs:
        pairs: list[tuple[float, int]] = []
        signed = False
        for r in t.rows:
            vals = [(_parse_value(c), c) for c in r]
            codes = [c.replace(" ", "") for c in r if _BIN_RE.match(c.replace(" ", ""))]
            numeric = [v for v, _ in vals if v is not None]
            if not numeric or not codes:
                continue
            value = numeric[0]
            code = int(codes[0], 2)
            if value < 0:
                signed = True
                continue  # two's-complement codes complicate slope; use positives
            pairs.append((value, code))
        # need two distinct positive points to derive the LSB weight
        uniq = sorted({(v, c) for v, c in pairs})
        if len(uniq) >= 2:
            (v1, c1), (v2, c2) = uniq[0], uniq[-1]
            if c2 != c1:
                lsb = round(abs((v2 - v1) / (c2 - c1)), 6)
                if lsb > 0:
                    unit = "°C" if any("C" in c for r in t.rows for c in r) else ""
                    return {"lsb_weight": lsb, "signed": signed, "unit": unit,
                            "pages": list(t.source_pages)}
    return None


def _lsb_from_prose(text: str) -> float | None:
    # "RESOLUTION: 10-Bit, 0.25°C" / "0.25 C resolution"
    m = re.search(r"resolution[:\s]*\d*\s*-?\s*bit[s]?[,\s]*(\d+\.\d+)", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+\.\d+)\s*°?\s*C\s+resolution", text, re.I)
    if m:
        return float(m.group(1))
    return None


def extract_readout(doc: Document) -> dict | None:
    """Extract fixed-readout parameters, or None if they cannot be determined
    with confidence (the caller must then BLOCK — never generate ungrounded)."""
    tabs = stitch_tables(doc, pages=None)
    bit_info = _find_bit_position_table(tabs)
    if bit_info is None:
        return None  # cannot determine the value bit-slice -> block

    lut = _find_value_code_table(tabs)
    text = " ".join(p.text or "" for p in doc.pages)
    signed_prose = bool(re.search(r"two.?s\s+complement", text, re.I))
    lsb_prose = _lsb_from_prose(text)

    lsb = (lut or {}).get("lsb_weight") or lsb_prose
    if lsb is None:
        return None  # cannot determine the scale factor -> block

    signed = bool((lut or {}).get("signed") or signed_prose)
    unit = (lut or {}).get("unit") or ("°C" if "°C" in text else "")
    # high confidence only when the table-derived slice/scale and prose agree
    corroborated = lut is not None and lsb_prose is not None and signed_prose
    return {
        "bit_width": bit_info["bit_width"],
        "value_msb": bit_info["value_msb"],
        "value_lsb": bit_info["value_lsb"],
        "signed": signed,
        "lsb_weight": lsb,
        "unit": unit,
        "source_pages": sorted(set(bit_info["pages"]) | set((lut or {}).get("pages", []))),
        "confidence": "high" if corroborated else "medium",
    }
