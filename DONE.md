# EmbeddPilot V1.1 — Status

## Verified Truths (V1.1)

These claims are currently true and demonstrable by running `python embeddpilot.py`:

- [x] **Extraction**: Sensor IR produced from Bosch BMP180 datasheet (BST-BMP180-DS000-12), schema-valid (28 registers, 6 commands, 11 coefficients, 7 timings). Blind PDF extraction accuracy: 194/194 (100%). See `extraction/EXTRACTION_NOTES.md`.
- [x] **Controller IR**: ESP32 I2C0 register map extracted from TRM Chapter 11, schema-valid (36 registers, 191 fields). See `PHASE_B_REPORT.md`.
- [x] **Harness discrimination**: Independent harness correctly distinguishes correct library (5/5 PASS) from broken library (3/5 FAIL). Proven in `PHASE_C_REPORT.md` Run 3.
- [x] **IR-grounded codegen**: Deterministic template generates driver from two-layer IR. Zero hardcoded sensor hex. IR mutations propagate to emitted code and are caught by harness. See `PHASE_D_REPORT.md`.
- [x] **Judge independence**: Generated library contains zero test logic (contamination guard enforced). Harness owns all expected values. Proven in `PHASE_C_REPORT.md` Runs 2-3.
- [x] **Compilation**: Generated driver compiles under PlatformIO (Arduino framework) without errors.
- [x] **Simulation**: Generated driver passes all 5 harness scenarios in Wokwi (BMP180 @ 0x77).
- [x] **Determinism**: Identical passing runs confirmed (deterministic template, no variance).
- [x] **Wrapper**: One-command interface (`python embeddpilot.py` → verified driver + proof).
- [x] **Extraction provenance**: Blind PDF extraction verified against prior IR (194/194 match). PDF is the arbiter. See `PHASE_E_REPORT.md`.

## V2 Roadmap (honest)

- [ ] **Runtime extraction at upload** — User uploads a datasheet PDF, extraction runs automatically. The schema is sensor-agnostic; the extraction pipeline needs generalization.
- [ ] **Multi-sensor generalization** — Support sensors beyond BMP180. The two-layer IR schema works for any I2C sensor; the driver template needs parameterization for different sensor APIs.
- [ ] **LLM-codegen decision** — Deferred until a real second sensor demands it. The deterministic template works for BMP180. Whether LLM generation adds value over parameterized templates is an empirical question that requires a second, structurally different sensor to answer.
