"""EmbeddPilot V1.5 ingestion: PDF/DOCX datasheet -> canonical register map JSON.

Pipeline stages:
  loader    - file -> per-page text + raw tables (50MB cap, scanned-page detection)
  sections  - classify pages: register/functional vs electrical/packaging/other
  tables    - stitch multi-page tables, drop repeated headers
  registers - parse stitched tables into registers + bit fields
  pipeline  - orchestrate and emit schema-valid register map JSON
"""

from ingestion.pipeline import ingest_datasheet

__all__ = ["ingest_datasheet"]
