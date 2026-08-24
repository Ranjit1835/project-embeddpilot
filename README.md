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

## LLM Providers & Environments (V1.7.1)

Generation uses one pluggable LLM provider, selected by configuration — no
vendor is hard-coded. `generation/provider.py::make_provider()` resolves it:

| Env var | Effect |
|---|---|
| `EMBEDDPILOT_PROVIDER=nvidia\|groq\|gemini` | Selects the provider explicitly (per environment, no code change) |
| _(unset)_ | Defaults to NVIDIA when `NVIDIA_API_KEY` is present, else Groq |

Keys are read from the environment only and are **never committed**
(`GROQ_API_KEY`, `NVIDIA_API_KEY`, `GEMINI_API_KEY`; `.gitignore` covers
`.env*`/`*.key`).

**Gemini (free tier).** `EMBEDDPILOT_PROVIDER=gemini` uses Google Gemini through
its OpenAI-compatible endpoint with a **free-tier flash model** (default
`gemini-3.6-flash`, ~1M-token context — the both-maps V1.7 job fits, like NVIDIA
and unlike Groq's ~8K free tier). Set `GEMINI_API_KEY`; override the model with
`GEMINI_MODEL` (keep it a free flash model). Free tier is rate-limited, so heavy
batch runs may hit 429s (the provider waits and retries).

### One generation path, no silent degradation

There is a single retry strategy: **targeted-edit** — on a failed attempt the
worker is handed its own prior failing file and told to fix only the validator-
named error. Before every request the pipeline checks the assembled prompt +
expected output against the provider's declared `context_window`; if it does not
fit it **fails loudly** (`provider-window-exceeded`) naming the provider, the
required size, and the limit. The device and MCU maps are never truncated and
the system never quietly falls back to a weaker strategy.

### Which provider where, and why

- **Local development / testing:** NVIDIA (`integrate.api.nvidia.com`,
  `openai/gpt-oss-120b`). Its ~128K window fits the V1.7 both-maps complete-
  driver job and the targeted-edit echo; Groq's ~8K free-tier admission window
  does not (a complete-driver job fails loudly there rather than degrading).
- **Deployed instance (concierge engineers):** NVIDIA's hosted developer
  endpoints (build.nvidia.com / integrate.api.nvidia.com) are licensed for
  *development, testing, research and evaluation* — serving real end-users falls
  under NVIDIA AI Enterprise, and the free tier is rate-limited (~40 req/min).
  **Do not hard-wire NVIDIA as the deployed production provider.** Configure the
  deployed environment via `EMBEDDPILOT_PROVIDER` with a provider licensed for
  serving end-users (e.g. a paid Groq/Together/Fireworks tier whose window fits
  the job, or NVIDIA AI Enterprise). The device-only (V1.6.x) flow fits Groq's
  window; the both-maps V1.7 flow needs a large-window licensed provider.

### Cost

Token cost is negligible (~$0.005 first-attempt / ~$0.016 per 3-attempt run;
under $1 for 50 runs/month) and identical across Groq/Together/Fireworks at
$0.15/$0.60 per 1M in/out. MCU reference-manual ingestion is deterministic and
cached (zero LLM tokens, one-time per MCU). See `V1.7.1_COST_ESTIMATE.md`.
