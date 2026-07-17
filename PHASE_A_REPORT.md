# EmbeddPilot V1 — PHASE A Diagnostic Findings

> Read-only architectural audit. Every claim backed by file:line evidence.

---

## 1. GENERATION NATURE

**VERDICT: Deterministic template expansion — no LLM at runtime**

The driver pipeline is pure string formatting. `codegen/driver_gen.py:42-213` is a single Python f-string that interpolates values from the `PeripheralIR` dataclass and a `sensor_config` dict. No HTTP client, no LLM SDK, no API key is imported or invoked anywhere in the codebase.

| Evidence | Location |
|----------|----------|
| Generator is one f-string template | `codegen/driver_gen.py:42-213` |
| Header generator is `lines.append(f"...")` | `codegen/header_gen.py:32-89` |
| IR parsed with `json.load()`, no network | `codegen/ir_parser.py:93-132` |
| Entry point chains parse→generate→write | `scripts/generate_driver.py:66-85` |
| Wrapper calls generate script via subprocess | `embeddpilot.py:68-76` |
| Only deps: streamlit, jsonschema | `requirements.txt:1-2`, `pyproject.toml:6-8` |
| Zero matches for openai/anthropic/llm imports | grep across all `.py` files |
| CLAUDE.md mandates determinism | `CLAUDE.md` — "same input must produce the same driver across runs" |

**Implication:** Generation is reproducible and auditable, but it also means the "AI pipeline" framing is aspirational — V1 is a deterministic template engine, not an LLM-driven generator.

---

## 2. JUDGE INDEPENDENCE

**VERDICT: Generator judges itself — the harness is not an independent oracle**

The project claims "the generator is NEVER the judge" (`CLAUDE.md:6`). The code contradicts this.

### How it actually works

1. `codegen/driver_gen.py:76-85` — the generator template embeds a `print_result()` function that emits `[PASS]`/`[FAIL]`
2. `codegen/driver_gen.py:126-190` — the template embeds all 5 test functions with their own expected values and assertion logic
3. `scripts/self_correct.py:54-59` — during verification, `driver.cpp` is **copied over** `harness/src/main.cpp` via `shutil.copy2()` — the reference driver is replaced, not consulted
4. `scripts/run_harness.py:70-88` — `parse_results()` is just `re.match(r"\[(PASS|FAIL)\]\s+(.+)", line)` — a regex text parser with zero independent expected values
5. The reference `harness/src/main.cpp` contains correct independent values (lines 16-24: `SENSOR_ADDR=0x77`, `EXPECTED_CHIP_ID=0x55`) but is **overwritten** before testing

### What IS independent

The Wokwi simulator itself provides a partial physical-layer check: the simulated BMP180 responds to I2C traffic according to its hardware model. Wrong I2C address → `Wire.endTransmission()` returns non-zero → real failure. But semantic assertions ("did we get the right chip ID?") are self-graded by the generator's own code.

### Trust boundary

```
Generator-owned (NOT independent):     Wokwi-owned (independent):
  - Expected chip ID value               - I2C bus ACK/NACK
  - Expected register readbacks           - Sensor response data
  - PASS/FAIL decision logic              - Bus timing/protocol
  - Test function structure               - Physical layer errors
```

**Implication:** A generated driver that checks the wrong expected value, or that always prints `[PASS]`, would pass the pipeline. The reference driver exists but plays no role during generated-driver testing.

---

## 3. GROUND TRUTH TARGET

**VERDICT: 11 documentation contradictions — BMP280→BMP180 migration was incomplete**

The working code is correct (BMP180, 0x77, 0x55). Five documentation files still reference BMP280.

### Contradictions

| # | File:Line | Says | Should Say | Severity |
|---|-----------|------|------------|----------|
| 1 | `CLAUDE.md:28` | `Sensor: BMP280 (virtual)` | `BMP180` | **HIGH** — instructs AI agents with wrong sensor |
| 2 | `DONE.md:3` | `virtual BMP280` | `BMP180` | MEDIUM |
| 3 | `README.md:42` | `Sensor: BMP280 (virtual)` | `BMP180` | MEDIUM |
| 4 | `harness/NOTES.md:5` | `0x76 for BMP280` | `0x77 for BMP180` | **HIGH** — wrong address |
| 5 | `harness/NOTES.md:6` | `chip ID = 0x58` | `0x55` | **HIGH** — wrong chip ID |
| 6 | `harness/NOTES.md:8` | `6 bytes` burst | `3 bytes` | MEDIUM |
| 7 | `harness/SETUP.md:53` | `ESP32 I2C0 + BMP280` | `BMP180` | **HIGH** |
| 8 | `harness/SETUP.md:57` | `chip_id=0x58` | `0x55` | **HIGH** |
| 9 | `harness/SETUP.md:59` | `ctrl_meas=0x27` | `0x20` | MEDIUM |
| 10 | `harness/SETUP.md:61` | `raw_press=..., raw_temp=...` | `raw_temp=29028` | LOW |
| 11 | `harness/SETUP.md:63` | `post-reset ctrl_meas=0x00` | `post-reset chip_id OK` | LOW |

### Clean files (consistent with BMP180)

`TARGET.md`, `harness/diagram.json`, `scripts/generate_driver.py`, `codegen/driver_gen.py`, `drivers/generated/driver.cpp`, `drivers/generated/i2c0_regs.h`, `harness/src/main.cpp`, `harness/reference/driver_broken.cpp`, `artifacts/register-ir.json`, `artifacts/pipeline_report.json`, `app.py`

**Implication:** `CLAUDE.md:28` is the most dangerous — it actively instructs AI agents to target BMP280 (address 0x76, chip ID 0x58/0x60), which would produce drivers that fail against the BMP180 simulator.

---

## 4. REGISTER MAP USAGE

**VERDICT: IR is decorative — the register map is extracted but never used in executable driver code**

### Data flow

```
register-ir.json
    │
    ├──→ header_gen.py ──→ i2c0_regs.h    ✅ REAL: offsets, masks, bit fields
    │                           │
    │                           ╳  DEAD END: nothing #includes this file
    │
    └──→ driver_gen.py ──→ driver.cpp
              │                 │
              │                 ├── Comments: IR metadata (peripheral name,
              │                 │   base address, register count)
              │                 │
              │                 └── Executable code: Wire library calls
              │                     with SENSOR_CONFIG values ONLY
              │
              └── SENSOR_CONFIG (hardcoded in scripts/generate_driver.py:34-48)
```

### Evidence

| Claim | Evidence |
|-------|----------|
| Header correctly generated from IR | `codegen/header_gen.py:44-72` — base_address, offsets, bit masks all from IR |
| Header is never included | `drivers/generated/driver.cpp:18-19` — only includes `<Arduino.h>` and `<Wire.h>` |
| Driver has no register-level access | No `0x3FF53000`, no `REG_READ`/`REG_WRITE` in driver.cpp executable code |
| IR flows into driver comments only | `codegen/driver_gen.py:21-50` — `ir_notes` and metadata used in `/* */` block |
| Sensor config is hardcoded, not from IR | `scripts/generate_driver.py:34-48` — `SENSOR_CONFIG` dict |
| Hallucination validator is a no-op | `scripts/generate_driver.py:107-127` — checks for hex not in IR, but driver has no register addresses to flag |

### Litmus test: change a register offset in register-ir.json

| Artifact | Would it change? |
|----------|-----------------|
| `i2c0_regs.h` | **YES** — #define offsets would update |
| `driver.cpp` comments | **YES** — register count and IR notes would update |
| `driver.cpp` executable code | **NO** — byte-for-byte identical |

**Implication:** The register map extraction (36 registers, 191 fields) is real and the header it generates is correct — but it's an orphan artifact. The driver operates at the Arduino Wire abstraction layer, which hides all ESP32 I2C controller registers behind library calls. The pipeline extracts the map, validates the map, generates a header from the map, then ignores the header.

---

## SYNTHESIS

### What V1 actually proves

1. **Template-driven codegen works** — deterministic generation from config → compilable, runnable C++ driver
2. **Wokwi simulation-in-the-loop works** — headless CI-friendly firmware verification is viable
3. **The pipeline plumbing works** — extract → generate → compile → simulate → report, with self-correction

### What V1 does NOT yet prove

1. **AI generation** — no LLM is involved at runtime; the driver is a filled-in template
2. **Independent verification** — the generated driver grades its own tests; the reference harness is overwritten
3. **Register-map-driven codegen** — the IR is extracted and validated but its data doesn't reach executable driver code
4. **Generalization** — hardcoded SENSOR_CONFIG means the pipeline works for BMP180 on ESP32 I2C, nothing else

### Recommended Phase B priorities

| Priority | Fix | Why |
|----------|-----|-----|
| P0 | Fix 11 BMP280→BMP180 doc contradictions | `CLAUDE.md:28` actively misguides AI agents |
| P1 | Make harness an independent judge | Reference main.cpp should own expected values; generated driver should be tested against harness assertions, not its own |
| P1 | Make driver.cpp `#include i2c0_regs.h` | Close the IR→driver data flow gap; use register addresses, not just Wire library |
| P2 | Add LLM-at-runtime generation | Replace template with prompted generation to prove the "AI pipeline" claim |
| P3 | Parameterize sensor config from IR or config file | Remove hardcoded SENSOR_CONFIG to enable multi-peripheral support |
