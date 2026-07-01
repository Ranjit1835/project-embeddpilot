# EmbeddPilot — Claude Code Instructions

## What this project is
An AI pipeline that turns MCU peripheral datasheets into simulation-verified C drivers. V1 targets ESP32 I2C + Wokwi.

## Architecture
- `schema/register-ir.schema.json` is the contract between extraction and codegen. Everything flows through it.
- 6 specialist agents in `.claude/agents/` — see each file for role and rules.
- The generator is NEVER the judge. Codegen agents do not verify their own output.

## Build order (mandatory)
1. Extraction (datasheet -> IR)
2. Verification harness (build judge first)
3. Codegen (IR -> driver)
4. Self-correcting loop (fix on failure)
5. Wrapper (user-facing interface)

## Rules
- Drivers must ONLY use registers present in the IR. Never generate register accesses from training memory.
- IR extraction must flag ambiguous fields as `"confidence": "low"` — never guess.
- All sim harness runs must be headless, single-command, CI-runnable with exit codes.
- Determinism is mandatory: same input must produce the same driver across runs.

## V1 Target
- MCU: ESP32-WROOM-32
- Peripheral: I2C0 (master mode)
- Simulator: Wokwi CLI
- Sensor: BMP280 (virtual)

## File conventions
- IR artifacts go in `artifacts/`
- Generated drivers go in `drivers/generated/`
- Reference drivers go in `harness/reference/`
- Datasheet PDFs go in `extraction/input/`
