# Phase D Report — IR-Grounded Generation

**Date:** 2026-07-02
**Verdict:** PASS

## Objective

Make every sensor constant in the generated driver come from a machine-readable IR file, not hardcoded hex literals. Exit bar: change an IR value, emitted code changes, harness catches it.

## Architecture: Two-Layer IR

| Layer | File | Schema | Contents |
|-------|------|--------|----------|
| Controller | `artifacts/controller-ir.json` | `schema/register-ir.schema.json` | ESP32 I2C0 peripheral: 36 registers, 191 bit fields |
| Sensor | `artifacts/sensor-ir.json` | `schema/sensor-ir.schema.json` | BMP180: 28 registers, 6 commands, 11 calibration coefficients, 7 timings |

## Files Changed

| File | Change |
|------|--------|
| `schema/sensor-ir.schema.json` | NEW — JSON Schema for I2C sensor register maps |
| `artifacts/sensor-ir.json` | NEW — BMP180 sensor IR extracted from datasheet |
| `codegen/sensor_ir_parser.py` | NEW — Typed parser for sensor IR (SensorIR, SensorRegister, SensorCommand, etc.) |
| `codegen/driver_gen.py` | REWRITTEN — Takes `(PeripheralIR, SensorIR)` instead of `(PeripheralIR, dict)`. All sensor constants from IR. |
| `scripts/generate_driver.py` | REWRITTEN — Loads both controller + sensor IR, passes both to codegen |
| `scripts/validate_ir.py` | UPDATED — Handles sensor IR schema (address vs offset, no bit-field checks) |
| `embeddpilot.py` | UPDATED — 7-step pipeline (was 6), sensor IR validation stage, `--sensor-ir` CLI arg |
| `CLAUDE.md` | UPDATED — Two-layer IR architecture documented |
| `DONE.md` | UPDATED — IR-driven executable code marked complete |

## Proof Runs

### 1. Determinism Proof (3/3 PASS)

All three consecutive pipeline runs produced identical output: 5/5 tests PASS, VERDICT: PASS.

### 2. Grep Proof

```
$ grep "0x[0-9A-Fa-f]{2}" codegen/driver_gen.py
→ Only match: 0xFF (uninitialized chip_id sentinel, not a sensor constant)
```

All 8 sensor constants (`0x77`, `0xD0`, `0x55`, `0xE0`, `0xB6`, `0xF4`, `0x2E`, `0xF6`) are IR-driven f-string substitutions.

### 3. IR Mutation Proof #1: `chip_id_expected` 0x55 → 0x66

- **IR change:** `"chip_id_expected": "0x55"` → `"0x66"`
- **Emitted code change:** `static const uint8_t EXPECTED_CHIP_ID = 0x66;`
- **Harness result:** SIM_FAIL — 2 tests failed (`test_i2c_init`, `test_soft_reset`)
- **Verdict:** IR mutation correctly propagated, harness correctly caught

### 4. IR Mutation Proof #2: `chip_id_register` 0xD0 → 0xD1

- **IR change:** `"chip_id_register": "0xD0"` → `"0xD1"`
- **Emitted code change:** `static const uint8_t REG_CHIP_ID = 0xD1;`
- **Harness result:** SIM_FAIL — 3 tests failed (`test_i2c_init`, `test_chip_id`, `test_soft_reset`)
- **Verdict:** IR mutation correctly propagated, harness correctly caught

### 5. Independence Check

`harness/src/main.cpp` was never modified during Phase D. All expected values remain harness-owned. The contamination guard passed on every run.

### 6. Restoration Proof

After both mutations were reverted, the pipeline returned to VERDICT: PASS, 5/5 tests.

## Pipeline Output (7 steps)

```
[1/7] Validating controller IR against schema...  PASS
[2/7] Validating sensor IR against schema...       PASS
[3/7] Generating driver library (deterministic)... PASS
[4/7] Running contamination guard...               PASS
[5/7] Compiling driver via PlatformIO...            PASS
[6/7] Running Wokwi simulation...                  5/5 PASS
[7/7] Packaging output...                          PASS
VERDICT: PASS
```

## Exit Bar Status

| Criterion | Status |
|-----------|--------|
| Sensor IR schema created and validated | PASS |
| BMP180 register map extracted to sensor IR | PASS (28 regs, 6 cmds, 11 coefficients) |
| Zero hardcoded sensor hex in driver_gen.py | PASS (grep: only 0xFF sentinel) |
| Change IR value → emitted code changes | PASS (both mutations verified) |
| Harness catches IR mutation | PASS (both mutations caught: 2 and 3 test failures) |
| Pipeline passes with correct IR | PASS (3/3 deterministic runs) |
| Harness never overwritten | PASS (independence preserved) |

## What Remains (Phase E)

- [ ] LLM-at-runtime generation (replace deterministic template with prompted LLM)
