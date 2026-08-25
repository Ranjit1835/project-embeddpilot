# EmbeddPilot V2 — Plan: Requirement → Complete Working Application Repo

**Owner:** Ranjit
**Written:** 2026-08-24 · **Start:** 2026-08-25 (spike first)
**Status:** PLAN — not started. First action tomorrow is the emulation spike + gate.

> Product-phase V2 (per `ROADMAP.md`). Prerequisite V1.10a (math verification /
> execution capability) is merged + deployed.

---

## 1. Goal (as set by the user)

From a **user-supplied requirement**, produce a **complete application repo + full
application code** — and the code must **actually work**, not merely compile.

## 2. The one rule that shapes everything

Nothing unverified is presented as verified. So **"working" cannot be asserted —
it must be demonstrated.** That single constraint forces the biggest design
decision in V2: **runtime verification (emulation) is part of V2**, not deferred.
Without it, "working code" is a hope, and shipping a hope is exactly what this
product exists to prevent.

## 3. Three honest tiers of "working"

| Tier | Meaning | Proof | In V2? |
|---|---|---|---|
| **Compiles** | whole repo builds; resources don't conflict | gcc / arm-none-eabi-gcc + the resource validator | yes (static floor) |
| **Runs (emulated)** | firmware executes; reads mocked sensors; app logic behaves per spec | **Renode** — emulate the MCU, mock the I²C/SPI devices returning known raw values (reuse the register maps / math oracle as the source of truth), run the firmware, assert the app's observable behavior | **YES — this is how V2 credibly claims "working"** |
| **Runs on hardware** | works on the physical board | flash + serial sanity — **needs a human** (physical wiring, board quirks) | **NO** — deferred to V5, honestly labeled |

**V2's definition of "working" = verified running in emulation.** Example DoD:
"the app reads BME280, computes temperature, and raises an alert over UART" —
demonstrated in Renode with a mocked sensor feeding known values and the UART
output asserted. The last mile to physical hardware stays a labeled human step.

## 4. What V1 gives us (reuse, don't rebuild)

- Per-device **verified drivers** (bus / MCU-complete / minimal / Arduino) — the composition units.
- The full grounding stack: register / readout / **math** crosschecks + compile, 3-state verdict, contamination guard, subprocess validator.
- `make_provider()` (NVIDIA / Groq / **Gemini free**) + the targeted-edit retry loop.
- The Next.js UI, the Railway backend, the deploy pipeline.

## 4b. Product direction refinements (user, 2026-08-25)

**(a) UI/UX is explicitly NOT "VS Code + a chat window."** It must be genuinely
beautiful and read as *embedded systems* — a lab-bench instrument, not an editor:
- The **board is the hero**, not a file tree. The Resource Map / pinout is the
  center of gravity: you look at your *system*, not a folder.
- Instrument aesthetic: phosphor-green on dark, oscilloscope / logic-analyzer
  language, rack + panel framing, LED status indicators, silkscreen-style labels.
- **Code is a panel you inspect, not a place you live** — no IDE file-tree as the
  primary surface.
- "Watch it run" reads like an **instrument readout** (scope trace), not a
  terminal tab.
- **No permanent chat rail.** Conversation is a *moment* (intake/clarification),
  never a sidebar you stare at.

**(b) Clarify before building — never invent a requirement.** The user submits a
requirement **doc or message**; if anything is ambiguous the system **asks
questions immediately**, and only starts once understanding is clear. This is the
**same DNA as V1.6** (which killed silent auto-fill: never invent chip/interface —
ask). At application scale: *never invent a requirement — ask.* WS1 therefore =
requirement → **ambiguity detection** → targeted clarifying questions → **spec
lock**. The spec is verifiable: every generated file traces to a spec line;
**no spec line ⇒ no code** (provenance, exactly as in V1).

**(c) "The code should never have errors."** Honest engineering translation:
we cannot guarantee an LLM never emits a wrong line — but we CAN guarantee
**nothing ships unless it passed verification.** Generate → validate →
targeted-edit retry → release ONLY on pass; if it cannot converge, say so plainly
instead of handing over broken code. For V2 the bar rises to: **whole-repo compile
clean + zero resource conflicts + emulation assertions pass.** In practice the user
gets error-free code in hand, because errors are caught and fixed *inside* the
loop. Promising "never generates errors" would assert unproven quality — the one
thing this product exists not to do. "Never ships unverified code" is the stronger
claim because it is provable.

## 5. Workstreams (six)

1. **Requirements → spec.** NL/structured requirement → a structured **application
   spec** (devices, behavior, target board, constraints). Start as a guided
   **structured form**; evolve toward conversational. This spec is the contract
   everything downstream verifies against.
2. **Composition + persistent project.** Run V1's driver pipeline **per device**
   (direct reuse), assemble into one **project workspace** (`drivers/`, `app/`,
   build system, config) that persists across iterations — replaces today's
   stateless jobs.
3. **System-integration validator (the static moat).** The system-level analog of
   `register_crosscheck`: **pin-mux conflicts, bus-address collisions,
   clock/DMA/IRQ contention** across composed devices. Builds a resource map;
   a conflict is a hard failure.
4. **App-code generation + whole-repo compile.** Glue / main-loop / task logic +
   a generated build system (Arduino / CMake / PlatformIO), compiling the entire
   repo. App business logic has no datasheet oracle → verified as
   *compiles + uses only declared resources + calls driver APIs correctly*, with
   behavior grounded by WS6, never asserted.
5. **Runtime verification — emulation (the make-or-break, the runtime moat).**
   Renode: emulate the target MCU, mock the composed devices on virtual buses
   (values sourced from the register maps / math oracle), run the generated
   firmware, and **assert app behavior against the spec.** This is what turns
   "compiles" into "works."
6. **UI/UX — a wonderful project workspace (first-class).** See §7.

## 6. Boundaries & sequencing

- **V2 ↔ V3:** emulation is pulled INTO V2 (required for "working"). V3 then
  deepens it — richer self-heal/bugfix at project scale, broader board coverage.
- **V2 ↔ V5:** physical flashing + on-hardware sanity stay V5 (human-in-loop,
  30–50% automatable), clearly labeled in the UI.
- **Build vs reuse:** build the V2 verification + composition core **natively
  first** (resource validator, project model, emulation harness, whole-repo
  compile) — that's the moat and is front-end-agnostic. Bolt an agent engine
  (Aider/OpenHands via V1-as-MCP) on **later** for the interactive UX.

## 7. UI/UX — the workspace era

The V1 4-screen wizard doesn't fit. V2 is a **persistent project workspace**,
Cursor-like:

- **Requirements builder** — guided spec panel (add devices, define behavior,
  board, constraints); never a blank page.
- **Resource Map (hero screen)** — a live pinout + bus map of the composed
  system, with **conflicts rendered as collisions** (pin clash, bus-addr
  collision, clock/DMA/IRQ contention lit red). Makes the moat *visible*.
- **"Watch it run" panel** — a virtual serial console / live output showing the
  emulated app actually reading a (mocked) sensor and reacting. The demo that
  sells it.
- **Project explorer (IDE-like)** — file tree of the generated repo, honesty
  overlays extended to app files (verified / unverified-line highlighting,
  per-file verdict badges, diff-review on regenerate).
- **Build & verdict rail** — whole-repo compile + every check state
  (register / readout / math / **resource** / **emulation**) + attempt timeline.
- **Design language** — elevate the dark phosphor-green instrument theme; the
  Resource Map + "watch it run" are the signature moments. Design-first:
  wireframes + design review (frontend-design skill / UI Designer + UX Architect)
  before code.

### Resource Map — hero screen (two states)

The two frames encode the whole V2 thesis visually: **State A** makes the static
moat *visible* (a double-booked pin lights red, one-click auto-fix); **State B**
makes *"working" honest* (the verdict rail reaches `WORKING (emulated)` only after
the emulation assertions pass, with the mocked sensor fed from V1's register map /
math oracle). The rail carries V1's honesty language up to the system level.

**State A — conflict detected**
```
┌─ EmbeddPilot ─────────────────────────────────────────  project: greenhouse ▾ ─┐
│  ① Requirements   ② Devices   ●③ Resource Map   ④ Code   ⑤ Run          ⚙ ◐ │
├────────────────────────────────────┬────────────────────────────────────────────┤
│  TARGET  STM32F4 · Nucleo-F411      │  DEVICES (3)                        + add  │
│  ┌──────────────────────────────┐  │  ┌──────────────────────────────────────┐ │
│  │            STM32F411          │  │  │ ● BME280   I²C1 @0x76   ✓ reg ✓ math  │ │
│  │                              │  │  │ ● SSD1306  I²C1 @0x3C   ✓ reg         │ │
│  │  PB6 ┤SCL ◀━━━━━━━┓ I²C1      │  │  │ ● Relay    GPIO PB6     ⚠ conflict    │ │
│  │  PB7 ┤SDA ◀━━━━━┓ ┃          │  │  └──────────────────────────────────────┘ │
│  │  PB6 ┤GPIO ⚠━━━━╋━┛          │  │                                            │
│  │  PA2 ┤USART2_TX ┃  (free)    │  │  ⚠ CONFLICTS (1)                           │
│  │  PA9 ┤          ┗━ 0x76,0x3C │  │  ┌──────────────────────────────────────┐ │
│  │                              │  │  │ PB6 double-booked                     │ │
│  │  clock: APB1 42MHz  DMA: ok  │  │  │   • I²C1_SCL  (BME280, SSD1306)       │ │
│  └──────────────────────────────┘  │  │   • GPIO out  (Relay)                 │ │
│  bus 0x76 BME280 · 0x3C SSD1306     │  │   → reassign Relay   [ auto-fix ▸PB5 ]│ │
│                                     │  └──────────────────────────────────────┘ │
├────────────────────────────────────┴────────────────────────────────────────────┤
│  ✓ register   ✓ readout   ✓ math   ⚠ resource (1)   ○ emulation (blocked)        │
└───────────────────────────────────────────────────────────────────────────────────┘
```

**State B — after auto-fix → emulation runs ("watch it run")**
```
┌─ EmbeddPilot ─────────────────────────────────────────  project: greenhouse ▾ ─┐
│  ① Requirements   ② Devices   ③ Resource Map   ④ Code   ●⑤ Run           ⚙ ◑ │
├────────────────────────────────────┬────────────────────────────────────────────┤
│  TARGET  STM32F4 · Nucleo-F411      │  ▶ EMULATION · Renode          ● running   │
│  ┌──────────────────────────────┐  │  ┌──── virtual UART (USART2) ───────────┐ │
│  │  PB6 ┤SCL ◀━━━━━━━┓ I²C1      │  │  │ boot: I²C1 @400kHz ok                 │ │
│  │  PB7 ┤SDA ◀━━━━━┓ ┃          │  │  │ BME280 id=0x60  ✓                     │ │
│  │  PB5 ┤GPIO ✓━━━┓ ┃ (relay)   │  │  │ t=24.81°C  rh=41%   [mock vec #3]      │ │
│  │  PA2 ┤TX ━━━━━━╋━╋━▶ console  │  │  │ t=31.05°C → THRESHOLD → relay=ON  ✓    │ │
│  │                ┗━┛ 0x76,0x3C │  │  │ assert: relay ON when t>30  ✓ PASS    │ │
│  │                              │  │  └──────────────────────────────────────┘ │
│  └──────────────────────────────┘  │  mocked sensor ▸ BME280 feeding raw vec    │
│  no conflicts · resources clean     │  from register map · 6/6 assertions pass   │
├────────────────────────────────────┴────────────────────────────────────────────┤
│  ✓ register  ✓ readout  ✓ math  ✓ resource  ✓ emulation  →  WORKING (emulated)   │
└───────────────────────────────────────────────────────────────────────────────────┘
```

## 8. How we start (spike-first — same discipline as V1.7/1.9/1.10a)

**The gate is the emulation loop.** Before building anything, prove one tiny app
end-to-end in Renode:

> A minimal generated firmware reads a **mocked** sensor over an emulated bus,
> prints/acts over emulated UART, and an **assertion on that output passes** —
> all headless, one command, exit code.

- **If the spike passes:** "working code" is real; build the six workstreams.
- **If it doesn't:** scope "working" down to *compiles + resource-checked* for V2
  and **say so plainly** — we don't fake it. Emulation then becomes V3.

Suggested first slice: **Arduino target** (core owns clock/GPIO — simplest
composition) OR **STM32F4** (harder, but exercises real pin-mux conflicts + the
MCU map — the juicier moat demo). Decide in §9.

## 9. Decisions — LOCKED 2026-08-25

1. **First target: STM32F4.** Best Renode support (Cortex-M; UART/I²C emulate
   cleanly) → lowest risk for the emulation gate, and the best moat demo (real
   pin-mux conflicts + the MCU map).
2. **Requirements intake: conversational NL from the start.** More ambitious —
   noted tradeoff: ambiguity at the foundation before the verification core is
   proven; the NL→spec step must itself be validated (spec is still the contract).
3. **Agent engine: deferred** (build the verification/composition/emulation core
   natively first; Aider/OpenHands via V1-as-MCP later).
4. **Spike scope: ambitious — 2 devices + resource conflict + auto-fix +
   emulated run + assertion.** Bigger surface, but proves composition + the
   static moat + the runtime moat in one gate.
5. **Design direction: evolve the instrument theme** (default; revisit if a
   bolder workspace redesign is wanted).
6. **Resource Map in the spike: YES** — prototype the hero screen with mocked
   conflict data alongside the emulation spike.

## 10. First action (2026-08-25) — the emulation gate-before-the-gate

Everything hinges on emulation being feasible **in this environment**. So the very
first step is a Renode feasibility check (mirroring the V1.10a compiler check):
can we install/run Renode and boot an STM32F4 image headless here? Only once that
is answered do we build the ambitious spike:

**Ambitious spike (STM32F4):** generate a 2-device app (e.g. BME280 + a relay/OLED)
that triggers a **resource conflict** → **auto-fix** → compiles → runs in **Renode**
with the sensor **mocked** from the register map / math oracle → **asserts** app
behavior over emulated UART — headless, one command, exit code. Plus a **Resource
Map** UI prototype on mocked conflict data.

Gate: pass → build the six workstreams; fail (esp. if Renode can't run here) →
scope V2's "working" to *compiles + resource-checked*, say so plainly, and move
emulation to V3. Report before any workstream build — the cadence that landed
V1.7 / V1.9 / V1.10a.
