"""Stage 2: classify pages so only register/functional content feeds generation.

Keyword scoring, not ML: deterministic, inspectable, and wrong in visible ways.
A page is register-relevant if register-signal score beats exclusion score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ingestion.loader import Document

REGISTER_SIGNALS = [
    (r"\bregister\s+map\b", 6),
    (r"\bmemory\s+map\b", 5),
    (r"\bregister\s+description", 5),
    (r"\bregister\s+summary\b", 5),
    (r"\bbit\s*fields?\b", 3),
    (r"\breset\s+value\b", 3),
    (r"\b0x[0-9A-Fa-f]{2,}\b", 1),          # per-occurrence, capped below
    (r"\b(R/W|RW|RO|WO)\b", 1),
    (r"\[\s*\d+\s*:\s*\d+\s*\]", 1),        # bit ranges like [7:0]
    (r"\baddress\s+offset\b", 4),
    (r"\bregisters?\b", 2),
]

EXCLUSION_SIGNALS = [
    (r"\belectrical\s+characteristics\b", 6),
    (r"\babsolute\s+maximum\s+ratings\b", 6),
    (r"\bordering\s+information\b", 5),
    (r"\bpackage\s+(outline|dimensions|information|marking)\b", 5),
    (r"\bsoldering\b", 4),
    (r"\btape\s+and\s+reel\b", 5),
    (r"\bpin\s+(configuration|assignment|description)s?\b", 3),
    (r"\bmoisture\s+sensitivity\b", 4),
    (r"\blegal\s+disclaimer\b", 5),
    (r"\brevision\s+history\b", 4),
]

PER_PATTERN_CAP = 8  # one signal repeated 50x shouldn't drown everything else


@dataclass
class PageClass:
    page: int
    register_score: int
    exclusion_score: int

    @property
    def is_register_page(self) -> bool:
        return self.register_score >= 4 and self.register_score > self.exclusion_score


def _score(text: str, signals: list[tuple[str, int]]) -> int:
    total = 0
    for pattern, weight in signals:
        hits = len(re.findall(pattern, text, flags=re.IGNORECASE))
        total += min(hits, PER_PATTERN_CAP) * weight
    return total


def classify_pages(doc: Document) -> list[PageClass]:
    out = []
    for page in doc.pages:
        # tables carry signal too; fold their cells into the scored text
        table_text = " ".join(
            cell for t in page.tables for row in t for cell in row if cell
        )
        text = f"{page.text} {table_text}"
        out.append(
            PageClass(
                page=page.number,
                register_score=_score(text, REGISTER_SIGNALS),
                exclusion_score=_score(text, EXCLUSION_SIGNALS),
            )
        )
    return out


def register_pages(doc: Document) -> list[int]:
    return [pc.page for pc in classify_pages(doc) if pc.is_register_page]
