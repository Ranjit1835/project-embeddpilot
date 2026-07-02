# EmbeddPilot — Claude Code Instructions

## Ground truth
FINDINGS.md is the architectural audit of record. When any doc conflicts with FINDINGS.md, trust FINDINGS.md.
PDF is the arbiter for sensor IR disputes — if sensor-ir.json disagrees with the datasheet, the datasheet wins.

## What this project is
A deterministic template engine that turns MCU peripheral datasheets into simulation-verified C drivers. Designed and built with Claude Code. V1.1 targets ESP32 I2C0 + BMP180 sensor on Wokwi.

## Architecture
- **Two-layer IR**: `schema/register-ir.schema.json` (controller) + `schema/sensor-ir.schema.json` (sensor). Controller IR describes the MCU peripheral (ESP32 I2C0, 36 registers). Sensor IR describes the I2C device (BMP180, 28 registers, 6 commands, 11 calibration coefficients).
- **IR-grounded generation** (Phase D): Every sensor constant in the generated driver comes from `artifacts/sensor-ir.json`. Zero hardcoded hex literals in `codegen/driver_gen.py`. Change an IR value, emitted code changes, harness catches it.
- **Extraction provenance** (Phase E): Sensor IR verified against BMP180 PDF via blind extraction (194/194 accuracy). Extraction notes at `extraction/EXTRACTION_NOTES.md`.
- 6 specialist agents in `.claude/agents/` — see each file for role and rules.
- PRINCIPLE — "generator is never the judge": RESTORED (Phase C). The generated library (bmp180_driver.h/.cpp) contains zero test logic, zero Serial prints, zero PASS/FAIL strings. A contamination guard mechanically enforces this on every pipeline run. The harness (harness/src/main.cpp) owns all expected values and test scenarios.

## Build order (mandatory)
1. Extraction (datasheet -> IR)
2. Verification harness (build judge first)
3. Codegen (IR -> driver via deterministic template)
4. Simulation verification (Wokwi CLI)
5. Wrapper (user-facing interface)

## Rules
- Drivers must ONLY use registers present in the IR. Never generate register accesses from training memory.
- IR extraction must flag ambiguous fields as `"confidence": "low"` — never guess.
- All sim harness runs must be headless, single-command, CI-runnable with exit codes.
- Determinism is mandatory: same input must produce the same driver across runs.

## V1.1 Target
- MCU: ESP32-WROOM-32
- Peripheral: I2C0 (master mode)
- Framework: Arduino (Wire library)
- Build: PlatformIO
- Simulator: Wokwi CLI
- Sensor: BMP180 (virtual, I2C address 0x77, chip ID 0x55)

## File conventions
- IR artifacts go in `artifacts/`
- Generated driver library goes in `drivers/generated/` (bmp180_driver.h, bmp180_driver.cpp, i2c0_regs.h)
- i2c0_regs.h is a validated extraction artifact — NOT consumed by the driver
- Driver API contract is in `contracts/DRIVER_API.md`
- Datasheet PDFs go in `extraction/input/`
- Extraction notes go in `extraction/EXTRACTION_NOTES.md`
