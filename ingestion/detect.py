"""Metadata detection from the datasheet's front matter (V1.6 Priority 2).

The ingestion pipeline already parses the document; this module reads the
chip/part-number, vendor, and interface(s) the datasheet *states about itself*
so the user does not retype what the document already says.

Discipline (identical to register extraction): every detected value carries a
confidence and `source_pages` evidence. Detection is a SUGGESTION, never a
decision — the pipeline pre-fills only high-confidence single values and marks
them `detected` (unconfirmed) so the review screen forces a human confirm.
Multi-interface devices are surfaced as a choice and never auto-picked.

This module NEVER invents a value: no match -> the field is simply absent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ingestion.loader import Document

# how many leading pages count as "front matter" (title/overview/features)
FRONT_PAGES = 6

# Known part-number families. A hit here is high confidence; the pattern is
# matched case-insensitively against front-matter text.
CHIP_FAMILIES: list[tuple[str, str]] = [
    (r"\bBME\s?280\b", "BME280"),
    (r"\bBMP\s?180\b", "BMP180"),
    (r"\bBMP\s?280\b", "BMP280"),
    (r"\bBME\s?680\b", "BME680"),
    (r"\bW25Q\d{2,3}[A-Z]{0,2}\b", None),   # keep the exact match (e.g. W25Q64JV)
    (r"\bESP32(?:-[A-Z0-9]+)?\b", None),
    (r"\bMPU-?6050\b", "MPU6050"),
    (r"\bADXL3\d{2}\b", None),
    (r"\bLSM6DS[A-Z0-9]+\b", None),
]

# Vendor keyword -> canonical name.
VENDORS: list[tuple[str, str]] = [
    (r"\bbosch\b", "Bosch"),
    (r"\bwinbond\b", "Winbond"),
    (r"\bespressif\b", "Espressif"),
    (r"\bstmicroelectronics\b", "STMicroelectronics"),
    (r"\bnxp\b", "NXP"),
    (r"\btexas\s+instruments\b", "Texas Instruments"),
    (r"\bmicrochip\b", "Microchip"),
    (r"\bnordic\s+semiconductor\b", "Nordic Semiconductor"),
    (r"\banalog\s+devices\b", "Analog Devices"),
    (r"\binfineon\b", "Infineon"),
    (r"\brenesas\b", "Renesas"),
    (r"\binvensense\b", "InvenSense"),
]

# Interface token -> canonical name. Aliases collapse to one canonical value so
# the review screen shows I2C/SPI/UART, never "TWI".
INTERFACES: list[tuple[str, str]] = [
    (r"\bI2C\b", "I2C"),
    (r"I²C", "I2C"),          # "I²C"
    (r"\bIIC\b", "I2C"),
    (r"\btwo[-\s]?wire\b", "I2C"),
    (r"\bTWI\b", "I2C"),
    (r"\bSPI\b", "SPI"),
    (r"\bUART\b", "UART"),
    (r"\bUSART\b", "UART"),
]

# a generic part number: letters then digits, e.g. LPS22HB, MAX30102, TMP117
GENERIC_PART = re.compile(r"\b[A-Z]{2,}[0-9]{2,}[A-Z0-9\-]*\b")


@dataclass
class Detected:
    value: str
    confidence: str            # high | medium | low
    source_pages: list[int]

    def to_json(self) -> dict:
        return {"value": self.value, "confidence": self.confidence,
                "source_pages": sorted(set(self.source_pages))}


def _front_matter(doc: Document) -> list[tuple[int, str]]:
    """(page_number, text) for the leading pages, in document order."""
    pages = sorted(doc.pages, key=lambda p: p.number)[:FRONT_PAGES]
    return [(p.number, p.text or "") for p in pages]


def _family_match(front: list[tuple[int, str]]) -> tuple[str, int, int] | None:
    """First known-family hit in the front matter, as (part, page, offset). For
    exact-keeping families (canonical None) the printed token is returned. The
    offset lets the caller rank it by title prominence against generic tokens."""
    for pattern, canonical in CHIP_FAMILIES:
        for n, text in front:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                part = canonical if canonical is not None else \
                    m.group(0).upper().replace(" ", "")
                return part, n, m.start()
    return None


def _detect_chip(front: list[tuple[int, str]]) -> Detected | None:
    """Identify the chip the document is ABOUT.

    B1 (V1.8): the exact printed part number the document is titled/subject on
    WINS over any known-family pattern. A family pattern that matches a DIFFERENT
    sibling part mentioned in the body (BMP180/BMP085 inside a BMP183 datasheet)
    must never override the title part. The subject part is the one printed
    FIRST in the front matter (the title block on page 1) — earliest
    first-occurrence, not raw frequency, is the reliable discriminator (a package
    code like WLCSP12 or a sibling mention repeats, but the title comes first).
    """
    first: dict[str, tuple[int, int]] = {}   # token -> earliest (page, offset)
    pages_of: dict[str, set[int]] = {}
    for n, text in front:
        for m in GENERIC_PART.finditer(text):
            tok = m.group(0).upper()
            if not _looks_like_part(tok):
                continue
            key = (n, m.start())
            if tok not in first or key < first[tok]:
                first[tok] = key
            pages_of.setdefault(tok, set()).add(n)

    # A curated family match is a candidate too — crucially it may name a part
    # the generic tokenizer cannot split (e.g. W25Q64JV starts with one letter).
    family = _family_match(front)
    if family:
        part, fn, foff = family
        key = (fn, foff)
        if part not in first or key < first[part]:
            first[part] = key
        pages_of.setdefault(part, set()).add(fn)

    if not first:
        return None

    # subject = the part printed earliest (title block). Family membership does
    # not boost a body sibling above the title part; position decides.
    tok = min(first, key=lambda t: first[t])
    page0 = first[tok][0]
    first_page = front[0][0] if front else None
    pages = sorted(pages_of.get(tok, {page0}))
    if page0 == first_page:
        conf = "high"
    else:
        conf = "medium" if len(pages) >= 2 else "low"
    return Detected(tok, conf, pages)


def _looks_like_part(tok: str) -> bool:
    # filter obvious non-parts: pure units/section noise. Require a letter+digit
    # mix of reasonable length and reject common false positives.
    if not (3 <= len(tok) <= 20):
        return False
    if tok in {"I2C", "SPI", "UART", "USART", "GPIO", "ADC", "PWM", "RGB",
               "USB2", "USB3", "LGA8", "3V3"}:
        return False
    return bool(re.search(r"[A-Z]", tok) and re.search(r"[0-9]", tok))


def _detect_vendor(front: list[tuple[int, str]]) -> Detected | None:
    for pattern, name in VENDORS:
        pages = [n for n, text in front if re.search(pattern, text, re.IGNORECASE)]
        if pages:
            return Detected(name, "high", pages)
    return None


def _detect_interfaces(front: list[tuple[int, str]]) -> list[Detected]:
    """All interfaces mentioned in the front matter. One hit -> high confidence
    (a clear single-bus device); several -> each medium, because the choice is
    genuinely the user's (BME280 is I2C *and* SPI)."""
    hits: dict[str, list[int]] = {}
    for pattern, canonical in INTERFACES:
        for n, text in front:
            if re.search(pattern, text):
                hits.setdefault(canonical, []).append(n)
    if not hits:
        return []
    confidence = "high" if len(hits) == 1 else "medium"
    return [Detected(name, confidence, pages) for name, pages in hits.items()]


def detect_metadata(doc: Document) -> dict:
    """Scan the front matter. Returns a dict with any of: chip, vendor,
    interfaces (list). Absent keys mean 'no evidence' — never a guess."""
    front = _front_matter(doc)
    out: dict = {}
    chip = _detect_chip(front)
    if chip:
        out["chip"] = chip.to_json()
    vendor = _detect_vendor(front)
    if vendor:
        out["vendor"] = vendor.to_json()
    interfaces = _detect_interfaces(front)
    if interfaces:
        out["interfaces"] = [d.to_json() for d in interfaces]
    return out


def shape_hint(base_address: str | None, n_registers: int, n_commands: int) -> dict:
    """Device-shape hint for the UI, computed from the assembled map. This is a
    HINT only — the router still routes from the map itself (Priority 2 rule).
    """
    if n_commands and n_registers <= 2:
        value, conf = "command_device", "high"
    elif base_address:
        value, conf = "memory_mapped_peripheral", "high"
    else:
        value, conf = "bus_attached_sensor", "medium"
    return {"value": value, "confidence": conf, "source_pages": []}
