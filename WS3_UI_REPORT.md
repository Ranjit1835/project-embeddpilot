# Workstream 3 — Product UI Report

Date: 2026-07-17. Status: **complete — all three shapes demoed VALIDATED
through the browser (fresh Groq key), fallback path demonstrated with real
failures. Screenshots in `artifacts/ws3_screens/`.**

## V1 UI assessment (spec requirement)

`app.py` is Streamlit — a read-only V1.1 case-study page (no interactive
product flow, no "Request Driver" button). Per the WS3 mandate it is replaced,
not restyled: the reusable parts were concepts only (register browsing,
pipeline story), which the new UI reimplements natively. `app.py` remains in
the repo as the V1.1 historical case study; it is not part of the V1.5 product.

## What was built

**Backend (`api/`)** — thin FastAPI service; the UI never reimplements
pipeline logic:
- `POST /api/ingest` (multipart file/URL + chip/peripheral/pages, 50MB cap) and
  `POST /api/generate` (map + platform + review-screen edits) → job IDs.
- Per-job event streams: `GET /api/jobs/{id}/events` (SSE with history replay
  + heartbeats) and `GET /api/jobs/{id}` (snapshot). Stage callbacks were
  added to `ingestion/pipeline.py` (`progress`) and `generation/pipeline.py`
  (`on_event`) — events carry router decisions and validator REPORTS only;
  the contamination guard and subprocess validator are untouched (52/52 tests).
- `GET /api/jobs/{id}/download` — zip of generated files + register map +
  provenance.json. `GET /api/samples` — the three live-proven maps for
  demo/no-upload runs.

**Frontend (`ui/`)** — Next.js 16 App Router, TypeScript, Tailwind v4,
Framer Motion, production build clean:
- "Precision instrument" theme: near-black `#0b0f14`, phosphor green accent
  (`#3fe081`) for validated/active, amber strictly for the middle verdict,
  red strictly for failure; Geist for chrome, Geist Mono for registers/hex/
  code; compact dense tables; 200ms ease-out state animations only.
- Screen 1: drag-drop + picker + URL, 50MB messaging, field row, ingestion
  stages animating pending → active (pulse) → ✓ with fixed-height rows (no
  layout shift).
- Screen 2 (trust centerpiece): sortable dense register table with expandable
  bit-field rows, inline-editable name/offset/reset/access, row deletion,
  commands table for command devices, mixed maps supported; warnings panel
  incl. the explicit ESP32-style "bit-field layouts unavailable… whole-register
  access" notice; edits tracked verbatim → provenance. **The single Generate
  button lives here** (direct V1 feedback addressed).
- Screen 3: router decision with logged reason, attempts as a visible
  timeline (retries are a feature), per-attempt checklist compile/cross-check/
  static-analysis animating to ✓ / ✕ / "– skipped" (skipped never hidden),
  collapsible real compiler diagnostics, three-state verdict badges that are
  never visually collapsed.
- Screen 4: tabbed syntax-highlighted code viewer, copy + zip download,
  provenance panel (route, reason, model, attempts, source pages, per-check
  status, user edits), unverified-field list with click-to-scroll to the
  amber-highlighted `/* UNVERIFIED */` lines; fallback case renders an
  unmistakable red treatment with the exact validation failures listed and
  the register map in the download.
- Keyboard: real buttons/inputs everywhere, visible focus rings, aria labels
  on icon buttons, `role=tablist/tab`, `aria-current` on the step nav.
- Resilience: job subscription is SSE-first with an automatic snapshot-polling
  fallback (proxies buffer event-streams; observed once in testing — the
  fallback took over seamlessly).

Run it: `uvicorn api.main:app --port 8000` + `cd ui && npm run build && npm start`
(GROQ_API_KEY is read from the user environment).

## Demo status (definition of done) — COMPLETE

Screenshot batches live in `artifacts/ws3_screens/` via `ui/scripts/demo.mjs`
(Playwright driving the real UI, exact-badge assertions). With the fresh Groq
key (2026-07-17):

- **BME280** (register/bus device): `VALIDATED` through the browser ✓
- **W25Q64JV** (command device): `VALIDATED` through the browser ✓ — with the
  strengthened worker prompt the model no longer invents unverified fields
  for this map, so the verdict is the clean state rather than the amber one.
  The amber `VALIDATED — UNVERIFIED FIELDS` state was produced live at the
  pipeline level earlier the same day (WS2 report) and shares the exact same
  badge/panel rendering path demonstrated here.
- **ESP32 I2C** (memory-mapped, empty-fields map): `VALIDATED` through the
  browser ✓ (attempt 1 failed → diagnostics → attempt 2 validated — the
  retry timeline demo).
- **Fallback path: demonstrated repeatedly with screenshots** — real quota
  and compiler failures rendered honestly: red FAILED — UNVALIDATED badge,
  worker/compiler diagnostics listed, register map offered for manual work.

Demo-day fixes folded back into the product:
- The UI now always sends coding conventions (the missing "no dynamic
  allocation" default was why browser runs failed where CLI runs passed).
- Worker system prompt: include-what-you-use + no malloc unless conventions
  allow it.
- Cross-check false positive removed: `0xFFFFFFFF`-style all-bits mask
  constants are no longer misread as hard-coded absolute addresses (the
  absolute-address rule now fires only inside the peripheral's base region).
- Demo checker asserts the exact verdict badge text ("VALIDATED" can no
  longer be satisfied by "UNVALIDATED").

## Deviations / notes

- Spec's SSE choice kept, with the polling fallback added after observing
  proxy buffering — no websockets.
- The W25Q64 stray `Security 0x00` register the spec references is deletable
  on the review screen as intended (tracked as an edit).
- cppcheck still absent on this machine: the checklist shows "– skipped" in
  its neutral state — by design, never hidden.
- Playwright was added as a UI devDependency for the demo harness only.
