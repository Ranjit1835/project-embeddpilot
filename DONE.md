# V1 Definition of Done

V1 is done when: feeding the ESP32 Technical Reference Manual (I2C chapter) into the pipeline produces a C driver for the ESP32 I2C0 peripheral that compiles under ESP-IDF, passes the Wokwi simulation harness (init, read, write, and error scenarios against a virtual BMP280), and does so reproducibly — same input produces the same correct driver across 10 consecutive runs with zero variance, as verified by the reliability auditor.

## Exit Criteria (all must be green)

- [x] Extraction: IR JSON produced from datasheet, schema-valid, validator verdict PASS
- [x] Harness: Wokwi sim discriminates correct vs broken drivers (reference 5/5 PASS, corrupted 4/5 FAIL)
- [x] Codegen: Generated driver compiles under PlatformIO without errors
- [x] Verification: Generated driver passes all 5 harness scenarios in Wokwi sim
- [x] Self-correction: Pipeline completes on first attempt (5/5 PASS)
- [x] Determinism: 10/10 identical passing runs confirmed (max-retries 2 absorbs API transients)
- [x] Wrapper: One-command interface (embeddpilot.py -> verified driver + proof out)
