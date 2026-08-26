/* The V2 backend contract, transcribed from what the API actually returns.

   Source of truth: `api/main.py` (`/api/v2/analyze`, `/api/v2/build`),
   `orchestration/v2_pipeline.py` (stage + status vocabulary) and
   `validator/resource_crosscheck.py` (`build_resource_map` output shape).
   These are wire types only — nothing here decides anything, and nothing here
   invents a field the backend does not send. */

/* --------------------------------------------------------------- check state */

/** The four states a validator check may report. They are deliberately NOT
    collapsible into a boolean:

      pass            the check ran and the system satisfied it
      fail            the check ran and the system did not
      not_applicable  there was nothing to check (e.g. one device, so nothing
                      to compose) — not a defect, and not evidence of anything
      skipped         the check could NOT run (no toolchain, no firmware) — the
                      question is still open

   `not_applicable` and `skipped` must never be rendered as `pass`, and never as
   each other. See RAIL_* in components/resource-map/verdict.tsx. */
export type CheckState = "pass" | "fail" | "not_applicable" | "skipped";

/** Pipeline stage states. `blocked` is stage-only: the spec stopped the run. */
export type StageState =
  | "pass"
  | "fail"
  | "blocked"
  | "skipped"
  | "not_applicable";

/* ------------------------------------------------------------------ analyze */

export interface V2Question {
  id: string;
  field: string;
  text: string;
  /** Only ever a closed vocabulary the project owns (interfaces, comparators,
      output targets). Never a suggested part number, board or threshold. */
  options: string[];
  blocking: boolean;
}

export interface V2Bus {
  kind?: string;
  instance?: string;
  address?: string | number;
  [key: string]: unknown;
}

export interface V2PinRef {
  pin: string;
  function?: string;
  shared?: boolean;
}

export interface V2Device {
  name: string;
  bus?: V2Bus;
  pins?: (V2PinRef | string)[];
}

/** One device's claim on one resource, as `build_resource_map` emits it. */
export interface V2Claim {
  device: string;
  resource: string;
  function: string;
  signal: string;
  instance: string;
  shared: boolean | null;
}

export interface V2ResourceMap {
  pins: Record<string, V2Claim[]>;
  buses: Record<string, ({ device: string } & V2Bus)[]>;
  dma: Record<string, V2Claim[]>;
  irq: Record<string, V2Claim[]>;
  device_count: number;
}

export interface V2Stage {
  stage: string;
  state: StageState;
  detail: string;
}

export interface V2Failure {
  check: string;
  message: string;
}

/** A spec value plus the receipt proving the user supplied it. There are only
    two provenances — "user" (said it) and "asked" (answered a question). */
export interface V2Field {
  value: unknown;
  provenance: "user" | "asked";
  evidence: string;
}

export interface V2SpecDevice {
  name?: V2Field | null;
  role?: V2Field | null;
  interface?: V2Field | null;
  address?: V2Field | null;
  pin?: V2Field | null;
}

export interface V2Spec {
  requirement_text?: string;
  target?: { board?: V2Field | null; mcu?: V2Field | null } | null;
  devices?: V2SpecDevice[];
  behaviors?: unknown[];
  constraints?: unknown[];
  failure_behavior?: V2Field | null;
  output_target?: V2Field | null;
  notes?: string[];
  dropped?: unknown[];
}

export interface AnalyzeResponse {
  /** "needs-clarification" | "blocked-resource-conflict" | "no-firmware"
      | "working-emulated" | "not-working" | "failed" | "incomplete" | ... */
  status: string;
  questions: V2Question[];
  devices: V2Device[];
  resource_map: V2ResourceMap | null;
  stages: V2Stage[];
  checks: Record<string, CheckState>;
  failures: V2Failure[];
  spec: V2Spec;
}

/* -------------------------------------------------------------------- build */

/** A console line rendered in the emulation bay. Live runs build these from the
    report's own notes and failures; the demo fixture carries a recorded UART
    transcript. Which one you are looking at is always labelled. */
export type LineTone = "dim" | "ink" | "good" | "warn" | "bad";

export interface ConsoleLine {
  t: string;
  text: string;
  tone: LineTone;
}

export interface BuildResult {
  status: string;
  /** "generated" | "fixture" | null — load-bearing: presenting a hand-written
      fixture as generated output would be a lie about what the system can do. */
  firmware_origin: string | null;
  stages: V2Stage[];
  devices: V2Device[];
  /** The sentence that says emulation is not hardware. Empty unless the run
      actually reached a working-emulated verdict. NEVER synthesised here. */
  verdict_note: string;
  derivation_notes?: string[];
  checks: Record<string, CheckState>;
  failures: V2Failure[];
  notes: string[];
}

export interface JobEnvelope {
  id: string;
  kind: string;
  status: "running" | "done" | "error";
  events: { ts: number; type: string; [key: string]: unknown }[];
  result: BuildResult | null;
  error: string | null;
}
