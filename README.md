# EmbeddPilot V1.1

**Real datasheets. Validated register maps. Verified drivers.**

EmbeddPilot is a case study in honest embedded tooling: a real sensor datasheet (Bosch BMP180) turned into a validated sensor IR, deterministically generated into a driver library, and verified by an independent simulation harness. Designed and built with Claude Code.

## Architecture: AI at Ingestion, Deterministic at Emission

```
Datasheet PDF (BMP180)
    |
    v  [agent-assisted extraction]
Sensor IR (28 registers, 6 commands, 11 calibration coefficients)
    +
Controller IR (ESP32 I2C0, 36 registers, 191 bit fields)
    |
    v  [deterministic f-string template — same input = same output]
Driver Library (bmp180_driver.h + bmp180_driver.cpp)
    |
    v  [contamination guard — zero test logic in library]
Independent Harness (5 scenarios, harness-owned expected values)
    |
    v  [Wokwi CLI simulation]
Verified Driver + Proof  (5/5 PASS)
```

**Two-layer IR:** Controller IR describes the MCU peripheral (ESP32 I2C0). Sensor IR describes the I2C device (BMP180). Every sensor constant in the generated driver comes from the sensor IR — zero hardcoded hex literals. Change an IR value, the emitted code changes, the harness catches it.

**Extraction accuracy:** First-pass blind PDF extraction matched prior knowledge-authored IR 194/194 fields (100%).

## Live Demo

[**View the live case study**](https://ranjit1835-project-embeddpilot-app-ldwvma.streamlit.app/)

## V1.1 Target

- **MCU:** ESP32-WROOM-32 (Arduino/Wire, PlatformIO)
- **Sensor:** BMP180 (I2C 0x77, chip ID 0x55)
- **Simulator:** Wokwi CLI (headless)

## Quick Start

```bash
# Full pipeline: validate → generate → guard → compile → simulate → package
python embeddpilot.py

# Dry run (skip simulation)
python embeddpilot.py --dry-run

# Custom IR paths
python embeddpilot.py --ir artifacts/controller-ir.json --sensor-ir artifacts/sensor-ir.json
```

## Project Structure

```
project-embeddpilot/
├── schema/                 # IR schemas (controller + sensor)
├── extraction/             # Datasheet PDFs + extraction notes
├── artifacts/              # IR JSON files + pipeline reports
├── codegen/                # Code generation (template + parsers)
├── harness/                # Independent verification harness (PERMANENT)
├── drivers/generated/      # Generated driver library
├── contracts/              # API contract (DRIVER_API.md)
├── scripts/                # Validation + generation scripts
├── app.py                  # Streamlit live case study
└── embeddpilot.py          # One-command pipeline
```

## Phase History

| Phase | What | Report |
|-------|------|--------|
| A | Read-only architectural audit | FINDINGS.md |
| B | Truth pass — make every claim honest | PHASE_B_REPORT.md |
| C | Independent judge + library form factor | PHASE_C_REPORT.md |
| D | IR-grounded generation (two-layer IR) | PHASE_D_REPORT.md |
| E | Extraction provenance + live case study | PHASE_E_REPORT.md |
