# Workstream 2 — LLM Generation Path Report

Date: 2026-07-15, live-verified 2026-07-17. Status: **built, tested (52/52), and
proven live end-to-end on both LLM framings.**

## Live run results (2026-07-17, groq/openai/gpt-oss-120b)

| Run | Framing | Outcome |
|---|---|---|
| W25Q64JV (command device) | command | `validated-with-unverified-fields` in 2 attempts — attempt 1 failed compile, validator diagnostics fed back, attempt 2 passed cross-check + `xtensa-esp32-elf-gcc -Wall -Wextra -Werror`. All 41 opcodes verified against the map; the one invented bit (`SECURITY_LOCK_BIT`) carried the required UNVERIFIED comment and was tagged with file/line/pages. |
| BME280 (I2C sensor) | register | `validated` in 1 attempt — 42-register bus driver, compile-clean, every offset/field cross-checked. |

Live-run lessons folded back into the code:
- Exact output **filenames are part of the worker contract** (the model invented its own `#include` name otherwise).
- **Bus-attached devices** (`base_address: null`) get a transfer-callback
  addressing contract; the memory-mapped `<PERIPH>_BASE` contract only applies
  when a base exists.
- **Feature-omission rule** in the system prompt: if the map lacks data a
  feature needs (BME280's nibble-split `dig_H4–H6`), omit the feature and say
  so in notes — this converted a repeated compile failure into a first-attempt pass.
- Cross-check opcode classification fixed: `..._CMD_READ_SECURITY_REG` is an
  opcode, not a register offset (`_CMD_` anywhere beats the `_REG` suffix).
- Groq free-tier realities: per-model TPM/TPD budgets (prompt slimming +
  `GROQ_MAX_TOKENS`), gpt-oss needs JSON mode off + `reasoning_effort=low`
  (now automatic); provider errors surface as graceful `ProviderError`s.
  Default model is now `openai/gpt-oss-120b` (override with `GROQ_MODEL`).

Implements the WS2 kickoff addendum (all three amendments) on top of the WS1
ingestion spike. Provider decision: **Groq** (user choice, 2026-07-15), behind a
pluggable interface so switching providers touches one file.

## What was built

| Piece | Where | Summary |
|---|---|---|
| `commands` schema (Amendment 2) | `schema/register-map.schema.json` | Optional top-level array: name, opcode, description, address_bytes, dummy_cycles, data_direction, source_pages |
| Command-table extraction | `ingestion/commands.py` | W25Q64-style instruction tables + BMP180-style measurement-value tables; runs before register classification so opcodes stop masquerading as registers |
| Router | `generation/router.py` | Template registry (chip+platform match → V1 path untouched) → else LLM path with register/command framing; every decision logged to `artifacts/router_log.jsonl` and labeled for the UI |
| Worker | `generation/worker.py`, `generation/provider.py` | Groq (`llama-3.3-70b-versatile` default, `GROQ_MODEL` env override), JSON-object output → header/source/example; prompt enforces the Amendment 1 & 3 contract |
| Validator (the judge) | `validator/` package | Subprocess (`python -m validator <dir> --map <json>`), inputs = files on disk + map + toolchain only. Compile (`-Wall -Wextra -Werror`, xtensa gcc for ESP32, arm-none-eabi/gcc fallback), register/opcode cross-check, cppcheck + volatile heuristic |
| Retry + fallback | `generation/pipeline.py` | 1 initial + max 3 retries, feedback = validator failure artifacts only; exhaustion returns `unvalidated` with failures + register map attached |

## Amendment compliance

1. **Three-state verdicts** — `validated` / `validated-with-unverified-fields` /
   `failed`, computed in `validator/report.py` and never collapsed. Field
   contradicting the map = hard fail; field absent from the map = tagged
   unverified (file, line, register, define, claimed bits) and REQUIRED to
   carry the `/* UNVERIFIED ... */` comment — an unmarked invented field is
   itself a hard failure. The worker prompt names each unknown-layout register
   individually ("fields for I2C_SR_REG are UNKNOWN...").
   Extra rule: a skipped compile or cross-check can never yield `validated` —
   a judge that didn't run passes no one.
2. **Commands** — schema + extraction shipped; W25Q64 output migrated
   (44 fake registers → 41 commands with opcodes, address-byte counts, data
   direction); BMP180 now also carries its 5 measurement commands
   (0x2E, 0x34, 0x74, 0xB4, 0xF4) alongside its 28/28 registers. Router
   detects command devices (commands present, ≤2 registers) and switches the
   worker to transaction-builder framing. Opcode cross-check enforced.
3. **Base/offset contract** — worker input states base_address + relative
   addressing explicitly, requires `<PERIPH>_BASE` parameterization; validator
   hard-fails hard-coded absolute addresses and wrong `*_BASE` values.

## Test evidence (52 passing)

- Router: template match, platform mismatch → LLM, register framing, command framing.
- Cross-check: match→validated; contradict→failed; absent+comment→unverified;
  absent-no-comment→failed; unknown offset→failed; unknown opcode→failed;
  known opcode→validated; absolute-address-under-relative→failed (addendum-required);
  base define checked both ways.
- Retry loop: seeded fail→retry→success (validator artifact verified inside the
  retry prompt); 4 failures → graceful `unvalidated` fallback with failures +
  map attached; template route never calls the LLM.
- **Command-device end-to-end (addendum-required):** W25Q64 map → mocked worker
  output → REAL subprocess validator: cross-check pass + actual compile with
  `xtensa-esp32-elf-gcc -Wall -Wextra -Werror` pass.
- Contamination guard: AST-level assertion that `validator/` imports nothing
  from `generation/` and vice versa; pipeline invokes the validator via
  subprocess only.
- WS1 regressions: BMP180 28/28, ESP32 36/36, all ingestion tests green;
  V1 template pipeline untouched.

## Deviations / known gaps

- **No live Groq run yet** — `GROQ_API_KEY` is not set on this machine. All
  LLM behavior is exercised via `MockProvider`. Set the key and run:
  `python -c "from generation..."` (or wire into the UI in WS3) for the first
  live generation.
- Addendum names `arm-none-eabi-gcc` as the compile toolchain; it is not
  installed here. The validator prefers the platform-appropriate compiler
  (xtensa for ESP32 — present and used in tests) and falls back honestly;
  `arm-none-eabi-gcc` is picked up automatically once installed.
- `dummy_cycles` is always null: datasheet tables show dummy BYTES, and cycles
  depend on bus width per mode — recorded in `description` instead of guessed.
- W25Q64 "Write Status Register" commands get `data_direction: read` because
  Winbond parenthesizes the input cell like an output; a stray `Security 0x00`
  register survives from a lock-table. Both are review-screen material.
- cppcheck: winget install attempted; until present, static analysis reports
  `skipped` and is surfaced in the report notes (never silently passed).
