# Running EmbeddPilot V2 locally

For engineers testing the requirement → verified application pipeline. Everything
runs on your machine; nothing is sent anywhere except to the model provider you
configure.

---

## 1. What you need

| Tool | Why | Without it |
|---|---|---|
| Python 3.11+ | the backend | nothing runs |
| Node 20+ | the UI | no interface (the API still works) |
| **an LLM API key** | reads your requirement | **every field is asked blind — see §5** |
| `arm-none-eabi-gcc` | cross-compiles the generated firmware | build stops at `compile: skipped` |
| **Renode** | *runs* the firmware | `emulation: skipped` — nothing can reach “working (emulated)”, which is the whole point |

The last two are what make a verdict mean anything. Without them the pipeline
still generates a repo, and says plainly that it could not prove it runs.

### Installing the two that matter

**arm-none-eabi-gcc**
- Debian/Ubuntu: `sudo apt install gcc-arm-none-eabi libnewlib-arm-none-eabi`
- macOS: `brew install --cask gcc-arm-embedded`
- Windows: install PlatformIO, or the ARM GNU toolchain, and put it on `PATH`

**Renode** — <https://github.com/renode/renode/releases> (the *portable* build
needs no .NET install). Either put `renode` on your `PATH`, or unpack it to
`.tools/renode_x/<version>/` inside the repo, or set `EMBEDDPILOT_RENODE=/path/to/renode`.

> On Linux Renode also needs ICU: `sudo apt install libicu-dev`. Without it Renode
> exits at startup with *“Couldn't find a valid ICU package”* and emulation fails.

---

## 2. Setup

```bash
git clone https://github.com/Ranjit1835/project-embeddpilot
cd project-embeddpilot

python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-api.txt

cd ui && npm install && cd ..
```

## 3. Configure a model provider

Copy `.env.example` to `.env` and fill in ONE provider. Keys are read from the
environment and are never committed, never sent to us, and never entered in the UI.

```bash
export EMBEDDPILOT_PROVIDER=gemini
export GEMINI_API_KEY=...          # free tier is enough
```

Gemini's free tier is sufficient for testing. Groq and NVIDIA are also supported
— see `README.md`. **Do not use `EMBEDDPILOT_PROVIDER=nvidia` with
`openai/gpt-oss-120b`: that model was retired on 2026-09-03 and every request
returns 410.**

## 4. Run it

Two terminals:

```bash
# backend
uvicorn api.main:app --port 8000

# ui
cd ui && npm run dev
```

Open <http://localhost:3000>. The workspace is at `/app`.

Check what your machine can actually do — **do this first**:

```bash
curl -s localhost:8000/api/v2/capabilities | python -m json.tool
```

Every tool should read `"available": true`. Anything false tells you which check
will report `skipped` later, and why.

## 5. If the requirement is not being read

If you give a fully detailed requirement and it still asks about every field, the
model could not be reached. The intake says so in red at the top:

> **the requirement was NOT read — every field below is being asked blind**

That is a provider problem (missing key, wrong provider, retired model), not the
product deciding your requirement was vague. Check §3.

## 6. What to expect

A run moves through: `spec → compose → resource → generate → compile → emulate`.

Verdicts you may see, and what each means:

| Verdict | Meaning |
|---|---|
| `needs-clarification` | genuine gaps; nothing is generated until they are answered |
| `blocked-resource-conflict` | two devices claim the same pin/address — it cannot physically work |
| `not-working` | it generated and ran, but did not behave as the spec requires |
| **`working-emulated`** | generated, compiled, booted on an emulated STM32F4 against mocked devices, and matched the expected output |

`working-emulated` means **verified in emulation — not evidence it works on
physical silicon.** Renode models a device's register interface, not its analogue
behaviour or timing. Bring-up on real hardware is still a human step.

The generated repo appears in the **CODE** panel and downloads as a zip:
`src/main.c`, `Makefile`, `link/stm32f4.ld`, `README.md`. It builds standalone
with `make`.

## 7. Reporting a bug

Please include:
1. the **exact requirement text** you gave
2. the **verdict** and the **stage list** from the run
3. the output of `/api/v2/capabilities`
4. anything in the run's notes — the pipeline is built to say *why* it stopped,
   so that text is usually the diagnosis

Issues: <https://github.com/Ranjit1835/project-embeddpilot/issues>

## 8. Known gaps (please don't file these)

- **UART devices** — only I²C and SPI are supported
- **Timers / state machines** — app logic is sample → compare → act
- **Flashing to hardware, dump-success prediction** — not built; V4/V5
- **Engineering-unit thresholds** are refused unless the device has a verified
  conversion. `temp > 30 C` on a BMP180 is rejected on purpose: that conversion
  lives in a datasheet figure we cannot extract, so we will not invent it. State
  the threshold in raw units.

## 9. Running the test suite

```bash
python -m pytest -q        # ~390 tests, several minutes (real compiles + emulation)
```

Tests that need Renode or `arm-none-eabi-gcc` skip cleanly when absent, so a pass
on a machine without them proves less. Check §4 first.
