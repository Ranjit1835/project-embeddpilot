# EmbeddPilot

**Datasheet -> Verified Peripheral Driver, Automatically.**

EmbeddPilot is an AI-powered pipeline that reads MCU peripheral datasheets and produces simulation-verified C drivers. Not "probably correct" — verified in simulation with proof.

## How It Works

```
Datasheet PDF
    |
    v
[Datasheet Extractor] -- extracts register map
    |
    v
Register-Map IR (JSON) -- the contract
    |
    v
[Extraction Validator] -- catches extraction errors
    |
    v
[Driver Codegen] -- generates C driver from IR only
    |
    v
[Wokwi Sim Harness] -- runs firmware against virtual hardware
    |
    v
[Verification Runner] -- pass/fail verdict with specifics
    |
    v (on fail)
[Self-Correcting Loop] -- feeds failure back to codegen, max 5 retries
    |
    v
Verified Driver + Simulation Proof Report
```

## V1 Scope

- **MCU:** ESP32 (ESP-IDF)
- **Peripheral:** I2C controller
- **Simulator:** Wokwi (headless CLI)
- **Sensor:** BMP280 (virtual)

See [TARGET.md](TARGET.md) for the full target lock and [DONE.md](DONE.md) for exit criteria.

## Project Structure

```
project-embeddpilot/
├── schema/                 # IR JSON Schema (the contract)
├── extraction/             # Datasheet PDF input + extraction logic
│   ├── input/              # Source datasheet PDFs
│   └── output/             # Raw extraction intermediates
├── codegen/                # Driver code generation logic
├── harness/                # Simulation verification harness
│   ├── reference/          # Hand-written reference drivers
│   └── scenarios/          # Test scenarios with assertions
├── drivers/
│   └── generated/          # AI-generated drivers
├── artifacts/              # Pipeline artifacts (IR JSON, reports)
├── scripts/                # Utility scripts (validation, benchmarks)
├── tests/                  # Unit and integration tests
└── .claude/agents/         # Specialist sub-agent definitions
```

## Key Principle

**The generator is never the judge.** The agent that writes the driver does not decide whether it passed. A separate verification agent + the Wokwi simulator decide. This is what makes the output trustworthy.

## Build Order

1. **Extraction first** (make-or-break: a wrong register map poisons everything)
2. **Verification harness** (build the judge before the thing being judged)
3. **Codegen** (generate the driver from validated IR)
4. **Self-correcting loop** (fix on failure, prove determinism)
5. **Usable wrapper** (one command: datasheet in, verified driver out)
