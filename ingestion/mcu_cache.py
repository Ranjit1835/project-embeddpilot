"""Per-MCU map cache (V1.7, piece 4).

Ingesting a 1700-page reference manual costs ~15s of section-targeted parsing
(minutes if whole-document), so it must be done ONCE per MCU and reused. The
cache is the round's real asset: a growing library of supported MCUs. Each
cached map records the reference manual + revision it came from, so a stale
revision can be detected and re-ingested.

Cache entries are keyed by (mcu_family, variant, peripheral) and stored as
schema-valid MCU maps under artifacts/mcu_cache/.
"""

from __future__ import annotations

import json
import os
import re

from ingestion.mcu_pipeline import build_mcu_map

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "artifacts", "mcu_cache",
)


def _slug(*parts: str) -> str:
    joined = "_".join(p for p in parts if p)
    return re.sub(r"[^A-Za-z0-9]+", "_", joined).strip("_").lower()


def cache_path(
    mcu_family: str, variant: str | None, peripheral: str, cache_dir: str | None = None
) -> str:
    return os.path.join(
        cache_dir or CACHE_DIR,
        _slug(mcu_family, variant or "", peripheral) + ".json",
    )


def load_cached(
    mcu_family: str, variant: str | None, peripheral: str,
    cache_dir: str | None = None,
) -> dict | None:
    path = cache_path(mcu_family, variant, peripheral, cache_dir)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_cached(mcu_map: dict, cache_dir: str | None = None) -> str:
    path = cache_path(
        mcu_map["mcu_family"], mcu_map.get("variant"), mcu_map["peripheral"], cache_dir
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mcu_map, f, indent=1)
    return path


def get_mcu_map(
    pdf_path: str,
    peripheral: str = "I2C",
    variant: str | None = None,
    mcu_family: str = "STM32F4",
    refresh: bool = False,
    cache_dir: str | None = None,
) -> dict:
    """Cached MCU map for (family, variant, peripheral). Builds from the RM and
    caches on first use; returns the cached copy thereafter. `refresh=True`
    forces a re-ingest (e.g. a new RM revision)."""
    if not refresh:
        cached = load_cached(mcu_family, variant, peripheral, cache_dir)
        if cached is not None:
            return cached
    mcu_map = build_mcu_map(pdf_path, peripheral=peripheral, variant=variant)
    save_cached(mcu_map, cache_dir)
    return mcu_map
