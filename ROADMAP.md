# EmbeddPilot — Product Roadmap (V1 → V5)

**Owner:** Ranjit
**Last updated:** 2026-08-24
**Status:** V1 ~80% (shipped/deployed via code-releases V1.5–V1.9); V2 next.

> **Terminology.** The **product phases V1–V5** below are *not* the same as the
> code releases `V1.5 … V1.9`. All of that shipped code lives *inside* product
> phase V1. When this doc says "V2", it means the product phase, not a code tag.

---

## 1. The vision

EmbeddPilot becomes a platform **like Cursor, but for embedded** — you give
requirements, and it produces drivers, driver configuration, application code,
compiles it, debugs it, fixes errors, and tests it **end to end**. After the
software side is solid, we extend into Edge-AI / TinyML-assisted **hardware
communication, dumping, on-device testing, and error-fixing** — accepting that
the hardware layer is only **30–50%** automatable because physical bring-up
needs a human in the loop.

The non-negotiable principle carried from every V1.x round:
**nothing unverified is ever presented as verified.** This is the moat — a
grounded, hardware-accurate engine that a generic AI coding tool cannot match.

---

## 2. The five phases

| Phase | Definition |
|---|---|
| **V1** | Complete driver code + driver configuration + UI |
| **V2** | Complete application repo + complete application code |
| **V3** | Complete project compiling at software level, execution, and bugfix |
| **V4** | Complete E2E testing of the application + probability of hardware-dumping success + expected-error report |
| **V5** *(optional for now)* | Complete code dumping to hardware + hardware communication + sanity |

---

## 3. Honest scorecard — where we actually are

| Phase | Status today | Honest % |
|---|---|---|
| **V1** — driver + config + UI | Shipped & deployed across bus sensors, MCU-complete drivers, minimal sensors, Arduino + bare-metal targets. Validator does register / readout / compile / static-analysis crosschecks. Live on Railway + Vercel. | **~80%** |
| **V2** — app repo + code | Only the seed exists: single driver + example stub + Arduino library scaffolding. No app logic, no multi-driver orchestration, no repo generation, no requirements-intake. | **~5–10%** |
| **V3** — compile + execute + bugfix | We compile *single* drivers and have a targeted-edit retry loop. No project-scale build; **no execution/emulation at all**. | **~25%** |
| **V4** — E2E test + dump-probability + error report | Validator checks are a form of testing; error reporting is honest. No runtime tests, **no probability model, no HIL data** to build one. | **~5%** |
| **V5** — dump + HW comm + sanity | Not started (correctly deferred). The 30–50% ceiling is realistic. | **0%** |

### The V1 verification debt (carries forward)
Compensation-math, MCU init sequences, and AF numbers are currently marked
*unverified* but never actually *verified*. At single-driver scale this is
honest and fine. **At application scale these errors compound** — a wrong shift
in temperature math silently corrupts everything downstream. Closing this is the
trust foundation for everything above.

---

## 4. Gaps in the original roadmap (additions)

1. **Requirements-intake / spec layer.** The pitch is *"just give requirements,"*
   but today the input is structured (datasheet upload + dropdowns), not natural
   language. Requirements → spec → plan → build is the **missing spine** and a
   prerequisite for V2, not part of it.
2. **The "like Cursor" interaction model.** Cursor is iterative — chat, edit,
   regenerate, diff-review, whole-project context. EmbeddPilot today is a
   one-shot wizard with stateless job runs. We need a **persistent "project"
   abstraction** before V2 works as a repo tool.
3. **System-integration / resource-conflict validation.** A real app shares one
   MCU across sensors + actuators + comms + storage. New validator needed for
   **pin-mux conflicts, bus-address collisions, clock-tree conflicts, DMA/IRQ
   arbitration**. Unique to V2.
4. **Emulation infrastructure (Renode / QEMU).** V3 "execution" and V4 "testing"
   are impossible without running code somewhere. **Renode** is the embedded
   standard (emulates many MCUs, mocks sensors on virtual I²C/SPI). Critical
   shared infra spanning V3–V4; the honest way to "execute" before touching HW.
5. **Feedback loop to *train* the V4 probability model.** "Probability of dumping
   success" can't be guessed — it needs real flash-outcome data from a
   **hardware-in-the-loop rig** (or at least emulation outcomes). This is where
   the Edge-AI / TinyML angle genuinely fits.
6. **Cost & model economics at repo scale.** Single-driver runs were
   ~$0.005–0.016. Application-scale, multi-file, agentic generation is 10–100×
   the tokens. Free-tier Groq/NVIDIA sizing won't hold — V2 needs a real budget
   and a stronger agentic loop.
7. **Actuator / safety correctness.** Sensors are read-only, low-risk. Once apps
   drive motors / relays / actuators, wrong code has physical consequences —
   needs an explicit safety gate.

---

## 5. Build-vs-reuse: the Cursor-clone question

**Decision: reuse an agent engine for the generic loop; do NOT fork a full IDE;
keep V1 as the moat.**

A Cursor clone gives us the **shell** (requirements front-door + iterative chat +
repo editing + generic compile/bugfix loop) — i.e. gap #1 and #2 above. It gives
us **zero embedded intelligence** (datasheet grounding, register/readout
crosschecks, real-toolchain cross-compile, emulation, dump-probability). That is
V1 and beyond — **the clone is the delivery truck, V1 is the cargo.**

**The clone is a commodity; it is not the differentiator.** Our defensibility is
the hardware-grounded verification no general clone has. Lightly skinning a clone
= just another AI-coding wrapper. We stay defensible only because V1 is bolted
inside.

### What a clone actually covers when connected to V1
| Phase | Coverage from a clone | Why |
|---|---|---|
| V2 | **~60%** | Scaffolds repos & writes app code, but doesn't know embedded constraints (no-malloc, real-time, peripheral orchestration, RAM/flash budgets) — we inject that. |
| V3 | **~50%** | The edit→run→fix loop is exactly what Aider/OpenHands do; but "run" for embedded = cross-compile + Renode/QEMU, which we wire in. |
| V4 | **~5%** | No generic clone does dump-probability or embedded E2E; needs *our* outcome data. |

### Candidate engines (don't fork an IDE — wrap an agent)
- **Aider** — CLI, git-native, superb repo-scale edit→compile→fix loop. Easiest
  to wrap; point its "run/test" command at our toolchain + Renode.
- **OpenHands** (ex-OpenDevin) — autonomous agent in a sandbox; closest to
  "requirements → whole project." Heavier.
- **Cline / Roo Code** — agentic VS Code extensions; good for in-editor UX with
  minimal fork burden.
- **bolt.diy** — in-browser full-stack builder; good for requirements→app
  front-door UX, weaker for embedded.

*(Repo facts — stars/license/MCP-support/activity — to be web-verified before
final selection; the above is from Jan-2026 knowledge.)*

### Recommended architecture
Expose **V1 as an MCP server / tool** and let a chosen agent engine orchestrate
it, instead of jamming V1 into a forked IDE:
1. V1 driver-engine → MCP tools (`ingest_datasheet`, `generate_driver`, `crosscheck`).
2. Add embedded tools: `cross_compile`, `run_in_renode`, `resource_conflict_check`.
3. Wrap **Aider or OpenHands** as the repo-scale loop, with those tools + an
   embedded-constraints system prompt.
4. Front-door (requirements chat) = extend the existing Next.js UI, or use the
   clone's.

This keeps us **front-end-agnostic**, makes V1 the reusable brain, and means we
customize ~20% (embedded glue) instead of building an agent from scratch.

---

## 6. Sequenced plan

### V1.10 — bridge round (2 short spikes) ← **next**
- **(a) Comp-math golden-vector verification** on one chip (BMP180): extract the
  datasheet's worked example (raw ADC → expected output) and *actually verify*
  the generated math. Turns "honest" into "correct." New crosscheck alongside
  `register_crosscheck` / `readout_crosscheck`. **Trust foundation — highest
  leverage.**
- **(b) Requirements → plan front-door prototype**: NL requirements → structured
  spec. The spine of the platform vision.

### V2 — application repo + code
- Persistent **project abstraction** (workspace state, not stateless jobs).
- Application-code generation on top of trustworthy drivers.
- **System-integration validator** (resource-conflict checks: pin-mux, bus
  address, clock tree, DMA/IRQ).
- Reuse an agent engine (Aider/OpenHands) via the MCP architecture in §5.

### V3 — project compile + execution + bugfix
- Project-scale cross-compile.
- **Renode-based execution** (mocked sensors on virtual buses).
- Self-heal / bugfix loop at repo scale (extends the V1 targeted-edit retry).

### V4 — E2E testing + dump-success probability + error report
- Emulation/HIL-driven E2E tests.
- Begin **collecting flash-outcome data** → train the dump-success probability
  model (Edge-AI / TinyML angle).
- Expected-error forecast report.

### V5 *(optional)* — dump + HW comm + sanity
- Real flashing (openocd / esptool / avrdude / pyocd).
- Serial/telemetry communication + on-device sanity checks.
- Accept the 30–50% human-in-loop ceiling.

---

## 7. Immediate next step

**Start the V1.10 bridge — specifically the comp-math golden-vector spike (6a).**
It's small, fits the existing validator architecture, and is the trust
foundation every later phase depends on. Run it as a feasibility spike + gate
decision first (same cadence as prior rounds), targeting **BMP180**.

## 8. Open decisions
- [ ] Web-verify agent-engine shortlist (Aider vs OpenHands vs Cline) on current facts.
- [ ] Confirm V1.10 scope: comp-math spike only, or comp-math + requirements front-door together.
- [ ] Budget/model choice for repo-scale generation (paid tier / larger-window provider).
- [ ] Emulation target selection for V3 (Renode first MCU).
