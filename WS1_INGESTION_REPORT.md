# Workstream 1 — PDF/DOCX Ingestion Spike Report

Date: 2026-07-13. Status: **spike complete, gate passed — recommend proceeding to Workstream 2.**

## What was built

`ingestion/` — a standalone pipeline: PDF/DOCX → canonical register-map JSON
(`schema/register-map.schema.json`, per the V1.5 spec). Stages:

| Stage | Module | What it does |
|---|---|---|
| Load | `loader.py` | pdfplumber text+tables per page, python-docx for DOCX, 50MB cap, scanned-page detection |
| Classify | `sections.py` | keyword-scored page classification: register/functional vs electrical/packaging |
| Stitch | `tables.py` | multi-page table continuation (repeated or absent headers), selective merged-cell fill |
| Parse | `registers.py` | three table shapes: register-index, bit-column memory maps, headerless salvage; MSB/LSB pairs |
| Textscan | `textscan.py` | `Register 21.3: NAME (0xNNNN)` heading extraction for TRM-style manuals |
| Orchestrate | `pipeline.py` | dedupe, relative/absolute address merge + base inference, confidence scoring, schema validation |

CLI: `python -m ingestion <file> [--chip X] [--peripheral Y] [--pages A-B] [--out map.json]`
Tests: `tests/test_ingestion.py` — 25 tests reproducing every real-datasheet pathology found. All pass.

## Results against 4 real vendor datasheets + 1 DOCX

| Datasheet | Style | Result |
|---|---|---|
| **BMP180** (Bosch, 31pp) | bit-column memory map + MSB/LSB calib table | **28/28 addresses, 28/28 names, 0 spurious** vs hand-verified V1 sensor IR |
| **ESP32 TRM** (Espressif, 705pp, I2C ch.) | summary table + heading/diagram descriptions | **36/36 addresses, 36/36 names, 0 spurious** vs V1 controller IR |
| **BME280** (Bosch, 60pp) | bit-column map + paired-address calib table | 42 registers, all addresses correct; all control-register bit fields exact (`osrs_t[7:5]`, `measuring[3:3]`, …). Missing: dig_H4–H6 (nibble-split across shared bytes — genuinely ambiguous layout) |
| **W25Q64JV** (Winbond, SPI flash) | instruction-set table | 44 opcodes extracted correctly — but they are **commands, not registers** (see finding 2) |
| Synthetic DOCX | standard header table | 4/4 with resets + access; provenance warning emitted |

Extraction confidence self-labeling was honest throughout: garbled cells produced
`null` + warnings rather than wrong values (strict hex policy: `stat0e0 h` → null,
never `0xE0`).

## Findings that affect Workstream 2

1. **Register-level extraction is solid; field-level is datasheet-dependent.**
   Sensor-style bit-column maps yield exact fields. TRM-style bit *diagrams*
   (rotated text) are unrecoverable via the text layer — ESP32 registers come
   out with correct name/offset/access but no fields. The register cross-check
   validator must therefore treat "field not in map" differently from "field
   contradicts map": absence of fields ≠ evidence of error. The review screen
   (WS3) is the mitigation for field-level gaps.
2. **Schema gap: command-based devices.** SPI flash "register maps" are opcode
   tables. The canonical schema has no `commands` concept — V1's sensor IR
   *does* (BMP180 measurement commands). Recommendation: add an optional
   `commands` array to the canonical schema in WS2 rather than mislabeling
   opcodes as registers. Flagged per spec rule instead of silently restructuring.
3. **Relative vs absolute addresses.** Vendor summaries mix peripheral-relative
   offsets and absolute mapped addresses. The pipeline infers the base from
   registers seen both ways and rebases the rest (warning emitted). The LLM
   worker should receive offsets + inferred base explicitly.
4. **OCR fallback is detection-only for now.** Scanned/image-only pages are
   detected and reported with page numbers (per spec: never silently proceed);
   actual OCR (pytesseract/Tesseract) is not wired up. None of the four test
   datasheets needed it. Proposed: wire it in WS3 alongside the upload UI,
   clearly labeled low-confidence.
5. **Section classifier earns its keep.** Electrical-characteristics tables
   were the main source of false registers before exclusion scoring + strict
   hex (decimal values like `20` are rise times, not address `0x14`).

## Known limitations (accepted for V1.5, surfaced via confidence labels)

- Nibble-split registers sharing a byte (BME280 dig_H4/H5) are skipped, not guessed.
- Registers described ONLY in prose (W25Q64 status register bits) are not extracted.
- DOCX "pages" are block indices, not print pages (warned in output).
- Access type is null when the datasheet's table simply doesn't state it (BMP180).

## Verification

- `python -m pytest tests/test_ingestion.py` → 25 passed
- V1 untouched: `scripts/validate_ir.py` → PASS for both IRs; no V1 files modified
  (ingestion is purely additive: `ingestion/`, `schema/register-map.schema.json`,
  `tests/test_ingestion.py`, debug scripts in `scripts/`)
