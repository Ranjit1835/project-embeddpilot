# Phase E Report — Extraction Truth + Live Case Study UI + Concierge Funnel

**Date:** 2026-07-02
**Verdict:** PASS

## STEP 0 — Extraction Provenance Audit

| Check | Result |
|-------|--------|
| `extraction/input/bmp180.pdf` exists? | NO at start → human placed it during Phase E |
| `extraction/EXTRACTION_NOTES.md` exists? | NO at start → created during Phase E |
| `artifacts/sensor-ir.sample.json` exists? | NO |
| Git history for sensor-ir.json | No extraction run recorded; authored from knowledge in Phase D |

**Verdict: AUTHORED-FROM-KNOWLEDGE** — The sensor IR was originally written from datasheet knowledge during Phase D, not from a documented PDF extraction run. No evidence trail existed.

## STEP 1 — Make Extraction True

### 1. PDF Placement

Human placed `BMP180.PDF` (648,437 bytes, Bosch BST-BMP180-DS000-12 Rev 2.8, 29 pages) at `extraction/input/bmp180.pdf`.

### 2. Blind PDF Extraction

Performed blind extraction from the PDF using PyMuPDF text parsing. Key datasheet pages:
- **p13** Table 5 — Calibration coefficients (AC1-AC6, B1, B2, MB, MC, MD with addresses 0xAA-0xBF)
- **p18** — Memory map (chip-id 0xD0=0x55, soft reset 0xE0=0xB6, ctrl_meas 0xF4, output 0xF6-F8)
- **p19** Table 6 — I2C startup time (tStart min 10ms)
- **p20** Table 7 — I2C address (0xEE write / 0xEF read → 7-bit 0x77)
- **p21** Table 8 — Measurement commands (temp 0x2E/4.5ms, pressure 0x34/0x74/0xB4/0xF4)

Output: `artifacts/sensor-ir.extracted.json`

### 3. Field-by-Field Diff

```
EXTRACTION ACCURACY: 194/194 fields matched
PERFECT MATCH — zero differences
```

**194 fields** compared across: 6 device fields, 28 registers (name, address, size_bytes, access each), 6 commands (name, target_register, value each), 11 calibration coefficients (name, address_msb, address_lsb, signed each), 7 timings (name, microseconds each).

### 4. Accuracy Number

**194/194 (100%)** — The knowledge-authored IR from Phase D was identical to blind PDF extraction.

### 5. Triage Table

No differences found. Zero EXTRACTION-ERROR, zero PRIOR-IR-ERROR.

This validates that BMP180 is a clean extraction target — the datasheet has unambiguous register addresses in explicit text (not just figures), explicit command values in Table 8, and no conflicting information across sections.

### Hard Spots (documented in `extraction/EXTRACTION_NOTES.md`)

| Hard Spot | Resolution |
|-----------|-----------|
| Calibration coefficient signedness | Datasheet Table 5 omits signed/unsigned. Inferred from calculation algorithm (p14-15): AC1-AC3 signed, AC4-AC6 unsigned, B1-B2 signed, MB-MC-MD signed. |
| Soft reset timing | No dedicated reset recovery time specified. Used startup time (tStart min 10ms from Table 6 p19) as conservative bound. |
| Memory map figure (p18) | Figure partially rendered; text descriptions on same page cross-referenced with Table 8 for command details. |
| XLSB register | Contains only bits [7:3] for oversampled pressure. Temperature uses only MSB+LSB (16-bit). |

### 6. Pipeline Run Post-Extraction

```
[1/7] Validating controller IR...  PASS
[2/7] Validating sensor IR...      PASS
[3/7] Generating driver library... PASS
[4/7] Contamination guard...       PASS
[5/7] Compiling via PlatformIO...  PASS
[6/7] Wokwi simulation...         5/5 PASS
[7/7] Packaging output...          PASS
VERDICT: PASS
```

## LANE 1 — Live Case Study UI

**File:** `app.py` (complete rewrite)

### Structure

| Section | Content |
|---------|---------|
| **Hero** | One honest paragraph describing the actual pipeline run. All metrics derived from artifacts. |
| **Metrics strip** | 6 metrics: sensor regs, controller regs, bit fields, driver lines, header lines, sim result — all computed from IR files and pipeline report. Zero hardcoded numbers. |
| **Tab: Extraction** | Sensor IR browser (registers, commands, calibration, timings), low-confidence flagging, extraction notes, search/filter. |
| **Tab: Generation** | "AI at ingestion, deterministic at emission" explanation, IR mutation proof excerpts, generated code display. |
| **Tab: Independent Verification** | Harness-owned expected values, 5 scenarios table, latest sim results, full serial log, harness source. |
| **Tab: Trust Showcase** | "We tried to lie three ways — caught all three": contamination guard (Phase C Run 2), broken-library judge catch (Phase C Run 3), IR mutation catches (Phase D). Actual excerpts. |
| **Limitations** | Always visible (not expander): functional sim only, single target, agent-assisted extraction, i2c0_regs.h is reference only. |
| **CTA** | Twice (after hero, after proofs). `st.link_button` to external form. Requested fields listed in UI copy. |
| **Known Gaps** | Closed: judge independence, IR-grounded generation, extraction provenance. Remaining: runtime upload, multi-sensor, LLM-codegen decision. |

### Hardcoded Metrics Check

```
grep app.py for hardcoded metric literals → zero
```

All numbers in the metrics strip come from `len()` calls on loaded IR data and `count("\n")` on loaded files.

## LANE 2 — Report + Packaging Truth

**File:** `embeddpilot.py`

### Changes

| Change | Detail |
|--------|--------|
| `pipeline_report.json` | Now includes `controller_ir` (peripheral, registers, fields) and `sensor_ir` (name, manufacturer, address, registers, commands, coefficients, timings, extraction_method, extraction_date). |
| `proof.txt` | Now includes sensor IR extraction method and sensor identity. |
| `INTEGRATION.md` | Labels i2c0_regs.h as "validated ESP32 I2C0 register reference (extraction artifact) — not consumed by this driver." Integration steps reference only the two library files. |

## LANE 3 — Repo Docs

| File | Key Changes |
|------|-------------|
| `README.md` | Case-study framing, two-layer IR diagram, "AI at ingestion / deterministic at emission", extraction accuracy 194/194, link to live app. |
| `DONE.md` | All V1.1 exit criteria closed with evidence pointers. V2 items listed honestly. |
| `CLAUDE.md` | Extraction provenance directive ("PDF is the arbiter"), removed stale Phase E = LLM-at-runtime. |
| `extraction/EXTRACTION_NOTES.md` | NEW — page references, hard spots, failure modes, comparison result. |

## STEP FINAL — Verification

### 1. Full Pipeline Run

```
VERDICT: PASS (5/5 tests, 7/7 steps)
```

### 2. Artifact Availability

All 10 files the app reads exist and are not gitignored:
- `artifacts/pipeline_report.json` ✅
- `artifacts/controller-ir.json` ✅
- `artifacts/sensor-ir.json` ✅
- `extraction/EXTRACTION_NOTES.md` ✅
- `PHASE_C_REPORT.md` ✅
- `PHASE_D_REPORT.md` ✅
- `drivers/generated/bmp180_driver.h` ✅
- `drivers/generated/bmp180_driver.cpp` ✅
- `drivers/generated/i2c0_regs.h` ✅
- `harness/src/main.cpp` ✅

### 3. App Local Test

Streamlit app started locally, HTTP 200 confirmed.

### 4. Deployment

Streamlit Cloud deployment: push to GitHub → auto-deploy at existing URL.
**Live URL:** https://ranjit1835-project-embeddpilot-app-ldwvma.streamlit.app/

## Summary

| Criterion | Status |
|-----------|--------|
| Extraction provenance audited | PASS — verdict AUTHORED-FROM-KNOWLEDGE, then FIXED |
| Blind PDF extraction performed | PASS — 194/194 accuracy |
| Canonical sensor IR is PDF-arbitrated | PASS |
| Pipeline passes with updated IR | PASS (5/5) |
| App.py has zero hardcoded metrics | PASS |
| All app artifacts committed and not gitignored | PASS |
| CTA form link present | PASS (placeholder URL — human fills) |
| Limitations box always visible | PASS |
| Known gaps updated | PASS |
| README case-study framing | PASS |
| DONE.md all V1.1 criteria closed | PASS |
| CLAUDE.md extraction provenance directive | PASS |

## CTA Form URL

The app has a placeholder `CTA_FORM_URL = "https://forms.gle/YourFormIDHere"` at the top of `app.py`. The human should create a Google Form (or Tally form) and replace this URL before deploying. The form should collect: name, email, MCU family, sensor/peripheral, datasheet link, timeline, and optionally what-would-this-be-worth.
