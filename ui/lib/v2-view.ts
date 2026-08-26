/* Backend response -> what the Resource Map draws.

   This is the ONLY place that turns pipeline JSON into geometry and copy, so
   there is exactly one rendering path. Demo mode does not bypass it: the demo
   fixture is an `AnalyzeResponse`/`BuildResult` like any other and goes through
   these same functions (lib/v2-demo.ts). One path means a demo cannot
   accidentally acquire a capability the live path lacks.

   THE RULE HERE: restate, never enrich. Every label, lamp and trace below is
   derived from a value the backend actually sent. Where the backend sent
   nothing, this module produces an explicit "nothing was claimed" statement
   rather than a plausible-looking default — a board drawn with invented pins
   would be the exact failure `resource_crosscheck` exists to prevent, moved
   into the renderer. */

import type {
  AnalyzeResponse,
  CheckState,
  V2Claim,
  V2Device,
  V2Failure,
  V2ResourceMap,
  V2Spec,
  V2Stage,
} from "./v2-types";

/* ------------------------------------------------------------ board model */

export type PinKind = "bus" | "uart" | "gpio" | "free" | "power" | "reserved";

export interface BoardPin {
  id: string;
  y: number;
  kind: PinKind;
  /** silkscreen function label */
  fn: string;
  /** who claims this pad */
  owner?: string;
  conflict?: boolean;
  wired: boolean;
}

export interface BoardDieBlock {
  label: string;
  note: string;
  y: number;
  h: number;
  lit: boolean;
  conflict?: boolean;
}

export interface BoardDevice {
  id: string;
  name: string;
  role: string;
  iface: string;
  addr?: string;
  y: number;
  h: number;
  status: "ok" | "conflict";
  /** short mono chips under the name — only restated backend facts */
  facts: string[];
}

export type NetTone = "bus" | "uart" | "gpio" | "alarm";

export interface BoardNet {
  id: string;
  d: string;
  tone: NetTone;
  dashed?: boolean;
  flow?: boolean;
  delay: number;
}

export interface BoardTarget {
  board: string;
  mcu: string;
  /** the artifact the spec asks for ("cmake-project"). Rendered as a labelled
      chip, never as silkscreen — we have no package/footprint data for any
      part, and printing something else in the package's place would read as
      one. */
  output: string;
}

export interface BoardModel {
  target: BoardTarget;
  pins: BoardPin[];
  die: BoardDieBlock[];
  devices: BoardDevice[];
  nets: BoardNet[];
  /** alarm caption in the free silkscreen, only when a failure names a resource */
  alarm: string | null;
  /** the honest line under the device stack */
  footnote: string;
  /** set when there is genuinely nothing to draw; the board says why */
  empty: string | null;
}

/* -------------------------------------------------------------- geometry */

const PIN_Y = [78, 112, 146, 180, 214, 248, 282, 316, 350, 384] as const;
const DIE_TOP = 66;
const DIE_BOTTOM = 412;
const DEV_TOP = 52;
const DEV_BOTTOM = 456;
const DIE_RIGHT = 410;
const DEV_LEFT = 570;

interface Slot {
  y: number;
  h: number;
}

function layout(n: number, top: number, bottom: number, maxH: number, gap: number): Slot[] {
  if (n <= 0) return [];
  const span = bottom - top;
  const h = Math.max(26, Math.min(maxH, (span - gap * (n - 1)) / n));
  const total = n * h + gap * (n - 1);
  const start = top + Math.max(0, (span - total) / 2);
  return Array.from({ length: n }, (_, i) => ({ y: start + i * (h + gap), h }));
}

/** Orthogonal run between two vertical edges. `midX` is staggered per net so
    parallel drops do not sit on top of each other. */
function elbow(y1: number, y2: number, midX: number): string {
  if (Math.abs(y1 - y2) < 0.5) return `M ${DIE_RIGHT} ${round(y1)} H ${DEV_LEFT}`;
  return (
    `M ${DIE_RIGHT} ${round(y1)} H ${round(midX)} ` +
    `V ${round(y2)} H ${DEV_LEFT}`
  );
}

const round = (n: number) => Math.round(n * 10) / 10;

/** Silkscreen lane between the pad column (x=118) and the die edge (x=250) is
    ~130px; at 8px with 0.6 tracking that is ~24 glyphs. SVG text does not wrap
    or ellipsize, so anything longer runs under the die — clip it here rather
    than let the renderer print over itself. */
function fit(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

/* ------------------------------------------------------- failure matching */

/** Does a failure message name this token? Word-ish boundaries, so "PB6" does
    not match "PB60" and a device called "RELAY" does not match "RELAYS". */
function named(messages: string[], token: string): boolean {
  if (!token) return false;
  const t = token.toLowerCase();
  return messages.some((m) => {
    const hay = m.toLowerCase();
    let i = hay.indexOf(t);
    while (i !== -1) {
      const before = i === 0 ? " " : hay[i - 1];
      const after = i + t.length >= hay.length ? " " : hay[i + t.length];
      if (!/[a-z0-9_]/.test(before) && !/[a-z0-9_]/.test(after)) return true;
      i = hay.indexOf(t, i + 1);
    }
    return false;
  });
}

/* --------------------------------------------------------------- helpers */

function fieldValue(f: { value: unknown } | null | undefined): string {
  const v = f?.value;
  return v === null || v === undefined ? "" : String(v);
}

function busKindTone(kind: string | undefined, instance: string): NetTone {
  const k = (kind || "").toLowerCase();
  if (k === "uart") return "uart";
  if (k) return "bus";
  const inst = instance.toUpperCase();
  if (inst.startsWith("USART") || inst.startsWith("UART") || inst.startsWith("LPUART"))
    return "uart";
  if (inst) return "bus";
  return "gpio";
}

function pinKindFor(claims: V2Claim[]): PinKind {
  const fn = (claims[0]?.function || "").toUpperCase();
  const inst = (claims[0]?.instance || "").toUpperCase();
  if (fn.startsWith("GPIO")) return "gpio";
  if (inst.startsWith("USART") || inst.startsWith("UART") || inst.startsWith("LPUART"))
    return "uart";
  if (inst) return "bus";
  return "gpio";
}

function normaliseDevicePins(dev: V2Device): { pin: string; function: string }[] {
  return (dev.pins || []).map((p) =>
    typeof p === "string"
      ? { pin: p, function: "" }
      : { pin: p.pin, function: p.function || "" },
  );
}

function addressText(value: string | number | undefined): string {
  if (value === undefined || value === null || value === "") return "";
  return String(value);
}

/* --------------------------------------------------------- the board model */

export function boardFrom(
  devices: V2Device[],
  resourceMap: V2ResourceMap | null,
  failures: V2Failure[],
  spec: V2Spec | undefined,
  target: BoardTarget,
): BoardModel {
  const messages = failures.map((f) => f.message);
  const rmap: V2ResourceMap = resourceMap ?? {
    pins: {},
    buses: {},
    dma: {},
    irq: {},
    device_count: devices.length,
  };

  /* -- header pads: one row per pin the composed system actually claims ---- */
  const pinNames = Object.keys(rmap.pins).sort();
  const shownPins = pinNames.slice(0, PIN_Y.length);
  const pins: BoardPin[] = shownPins.map((name, i) => {
    const claims = rmap.pins[name] || [];
    const owner = claims
      .map((c) => (c.function && c.function !== "(unspecified)"
        ? `${c.device} as ${c.function}`
        : c.device))
      .join(" · ");
    return {
      id: name,
      y: PIN_Y[i],
      kind: pinKindFor(claims),
      fn: fit(
        claims[0]?.function && claims[0].function !== "(unspecified)"
          ? claims[0].function
          : "— function not stated",
        22,
      ),
      owner: owner ? fit(owner, 24) : undefined,
      conflict: named(messages, name),
      wired: true,
    };
  });

  /* -- the die: one block per peripheral the system actually claims -------- */
  const busInstances = Object.keys(rmap.buses).sort();
  const dmaKeys = Object.keys(rmap.dma).sort();
  const irqKeys = Object.keys(rmap.irq).sort();
  const gpioPinCount = pinNames.filter((p) =>
    (rmap.pins[p] || []).some(
      (c) => (c.function || "").toUpperCase().startsWith("GPIO") || !c.instance,
    ),
  ).length;

  interface DieSeed {
    label: string;
    note: string;
  }
  const seeds: DieSeed[] = [];
  for (const inst of busInstances) {
    const entries = rmap.buses[inst] || [];
    const kind = String(entries[0]?.kind || "").toLowerCase();
    seeds.push({
      label: inst,
      note: `${kind || "bus"} · ${entries.length} device${entries.length === 1 ? "" : "s"}`,
    });
  }
  if (gpioPinCount > 0)
    seeds.push({
      label: "GPIO",
      note: `${gpioPinCount} pin claim${gpioPinCount === 1 ? "" : "s"}`,
    });
  for (const k of dmaKeys) seeds.push({ label: k, note: `${(rmap.dma[k] || []).length} claimant(s)` });
  for (const k of irqKeys) seeds.push({ label: k, note: `${(rmap.irq[k] || []).length} claimant(s)` });

  const dieShown = seeds.slice(0, 7);
  const dieSlots = layout(dieShown.length, DIE_TOP, DIE_BOTTOM, 40, 12);
  const die: BoardDieBlock[] = dieShown.map((s, i) => ({
    label: s.label,
    note: s.note,
    y: dieSlots[i].y,
    h: dieSlots[i].h,
    lit: true,
    conflict: named(messages, s.label),
  }));
  const dieIndex = new Map(die.map((b, i) => [b.label.toUpperCase(), i]));

  /* -- devices ------------------------------------------------------------ */
  const specDevices = spec?.devices ?? [];
  const devShown = devices.slice(0, 8);
  const devSlots = layout(devShown.length, DEV_TOP, DEV_BOTTOM, 86, 14);
  const boardDevices: BoardDevice[] = devShown.map((d, i) => {
    const sd = specDevices[i];
    const devPins = normaliseDevicePins(d);
    const instance = String(d.bus?.instance || "").toUpperCase();
    const addr = addressText(d.bus?.address);
    const conflict = named(messages, d.name);

    const facts: string[] = [];
    if (d.bus?.kind) facts.push(String(d.bus.kind).toUpperCase());
    if (addr) facts.push(`addr ${addr}`);
    for (const p of devPins)
      facts.push(p.function ? `${p.pin} · ${p.function}` : p.pin);
    if (!facts.length) facts.push("no bus or pin stated");

    return {
      id: `${d.name}-${i}`,
      name: d.name,
      role: fieldValue(sd?.role) || "role not stated",
      iface: instance || (devPins[0] ? `GPIO ${devPins[0].pin}` : "unassigned"),
      addr: addr || undefined,
      y: devSlots[i].y,
      h: devSlots[i].h,
      status: conflict ? "conflict" : "ok",
      facts,
    };
  });

  /* -- nets: die block -> device block ------------------------------------ */
  const nets: BoardNet[] = [];
  devShown.forEach((d, i) => {
    const instance = String(d.bus?.instance || "").toUpperCase();
    const devPins = normaliseDevicePins(d);
    const key = instance || (devPins.length ? "GPIO" : "");
    const blockIdx = key ? dieIndex.get(key) : undefined;
    if (blockIdx === undefined) return;
    const block = die[blockIdx];
    const dev = boardDevices[i];
    const conflict = dev.status === "conflict" || block.conflict;
    nets.push({
      id: `${dev.id}-net`,
      d: elbow(block.y + block.h / 2, dev.y + dev.h / 2, 496 + i * 9),
      tone: conflict ? "alarm" : busKindTone(d.bus?.kind, instance),
      dashed: !instance,
      flow: !conflict,
      delay: 0.35 + i * 0.06,
    });
  });

  /* -- captions ----------------------------------------------------------- */
  const alarm = failures.length
    ? `⚠ ${failures.length} RESOURCE CONFLICT${failures.length === 1 ? "" : "S"} REPORTED`
    : null;

  const footParts: string[] = [];
  if (busInstances.length)
    footParts.push(
      busInstances
        .map((inst) => {
          const entries = rmap.buses[inst] || [];
          const addrs = entries
            .map((e) => (e.address !== undefined ? `${addressText(e.address)} ${e.device}` : e.device))
            .join(" · ");
          return `${inst}: ${addrs}`;
        })
        .join("   |   "),
    );
  if (!pinNames.length)
    footParts.push(
      "NO PIN CLAIMS IN THE SPEC — PIN-MUX AND AF CAPABILITY NOT VERIFIED",
    );
  if (pinNames.length > shownPins.length)
    footParts.push(`+${pinNames.length - shownPins.length} MORE PIN CLAIMS NOT SHOWN`);
  if (devices.length > devShown.length)
    footParts.push(`+${devices.length - devShown.length} MORE DEVICES NOT SHOWN`);
  if (seeds.length > dieShown.length)
    footParts.push(`+${seeds.length - dieShown.length} MORE PERIPHERAL CLAIMS NOT SHOWN`);

  const empty =
    devices.length === 0
      ? "No devices composed yet — the spec has not named anything to place on this board."
      : null;

  return {
    target,
    pins,
    die,
    devices: boardDevices,
    nets,
    alarm,
    footnote: footParts.join("   ·   "),
    empty,
  };
}

/** The board/MCU the run actually targets, read off the spec. Never a default:
    an unanswered target is drawn as unstated, because "STM32F411RE" printed on
    silkscreen for a run that never named one is an invented fact. */
export function targetFrom(spec: V2Spec | undefined): BoardTarget {
  return {
    board: fieldValue(spec?.target?.board) || "BOARD NOT STATED",
    mcu: fieldValue(spec?.target?.mcu) || "MCU NOT STATED",
    output: fieldValue(spec?.output_target),
  };
}

export function boardFromAnalyze(res: AnalyzeResponse): BoardModel {
  return boardFrom(
    res.devices,
    res.resource_map,
    res.failures,
    res.spec,
    targetFrom(res.spec),
  );
}

/* ------------------------------------------------------------ verdict rail */

/** The rail's states. The backend's four, plus two the UI owns for a run that
    is in flight or has not started. Each renders distinctly — see RAIL_STYLE. */
export type RailState = CheckState | "running" | "pending";

export interface RailItem {
  id: string;
  label: string;
  state: RailState;
  note: string;
}

/** check id -> the pipeline stage that runs it, so the rail can quote the
    backend's own detail line instead of a phrase we made up. */
const CHECK_STAGE: Record<string, string> = {
  resource_crosscheck: "resource",
  emulation_check: "emulate",
  register_crosscheck: "register",
  readout_check: "readout",
  math_crosscheck: "math",
};

/** What each state MEANS. These are restatements of the check contracts in
    validator/resource_crosscheck.py, not verdicts of our own. */
const STATE_NOTE: Record<RailState, string> = {
  pass: "checked · no findings",
  fail: "conflict reported",
  not_applicable: "nothing to check",
  skipped: "could not run — still unknown",
  running: "running…",
  pending: "not reached",
};

function humanCheck(id: string): string {
  return id
    .replace(/_crosscheck$/, "")
    .replace(/_check$/, "")
    .replace(/_/g, " ");
}

export function railFrom(
  checks: Record<string, CheckState>,
  stages: V2Stage[],
  failures: V2Failure[],
): RailItem[] {
  const byStage = new Map(stages.map((s) => [s.stage, s]));
  return Object.entries(checks).map(([id, state]) => {
    const stage = byStage.get(CHECK_STAGE[id] ?? id);
    const failureCount = failures.filter((f) => f.check === id).length;
    let note = STATE_NOTE[state] ?? state;
    if (state === "fail" && failureCount)
      note = `${failureCount} finding${failureCount === 1 ? "" : "s"}`;
    else if (stage?.detail && state !== "pass") note = stage.detail;
    return { id, label: humanCheck(id), state, note };
  });
}

/* ----------------------------------------------------------------- verdict */

export type VerdictTone = "good" | "bad" | "warn" | "idle";

export interface Verdict {
  label: string;
  tone: VerdictTone;
}

/** Every verdict the screen can show, keyed by a status the backend returned.
    There is no branch that produces a verdict from anything else — an unknown
    status is echoed verbatim rather than being smoothed into a familiar one. */
export function verdictFor(
  status: string | null,
  failures: V2Failure[],
  blockingQuestions: number,
): Verdict {
  if (!status) return { label: "AWAITING REQUIREMENT", tone: "idle" };
  const n = failures.length;
  switch (status) {
    case "needs-clarification":
      return {
        label: `SPEC INCOMPLETE — ${blockingQuestions} QUESTION${blockingQuestions === 1 ? "" : "S"} OPEN`,
        tone: "warn",
      };
    case "blocked-resource-conflict":
      return {
        label: `BLOCKED — ${n} RESOURCE CONFLICT${n === 1 ? "" : "S"}`,
        tone: "bad",
      };
    case "blocked-no-read-plan":
      return { label: "REFUSED — NOTHING READABLE IN THE MAP", tone: "bad" };
    case "no-firmware":
      return { label: "NOT BUILT — NO FIRMWARE SOURCE", tone: "warn" };
    case "incomplete":
      return { label: "INCOMPLETE — EMULATION NOT ATTEMPTED", tone: "warn" };
    case "failed":
      return { label: "FAILED", tone: "bad" };
    case "not-working":
      return { label: "NOT WORKING", tone: "bad" };
    case "working-emulated":
      return { label: "WORKING (EMULATED)", tone: "good" };
    default:
      return { label: status.replace(/[-_]/g, " ").toUpperCase(), tone: "warn" };
  }
}

/* --------------------------------------------------------------- conflicts */

export interface ConflictRecord {
  id: string;
  check: string;
  /** the resource the backend named, pulled out of its own message */
  resource: string;
  /** the backend's message, verbatim — including its own suggested remedy */
  message: string;
}

const RESOURCE_PATTERNS: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^pin ([A-Z]+\d+) double-booked/i, (m) => `pin ${m[1].toUpperCase()}`],
  [/^pin ([A-Z]+\d+) cannot provide/i, (m) => `pin ${m[1].toUpperCase()}`],
  [/^bus address (0x[0-9a-f]+) on (\w+)/i, (m) => `${m[1]} on ${m[2].toUpperCase()}`],
  [/^bus instance (\w+)/i, (m) => `bus ${m[1].toUpperCase()}`],
  [/^bus configuration contention on (\w+)/i, (m) => `bus ${m[1].toUpperCase()}`],
  [/^(DMA|IRQ) (?:resource|line) (\S+)/i, (m) => `${m[1].toUpperCase()} ${m[2]}`],
  [/^(\S+) declares/i, (m) => m[1]],
];

export function conflictsFrom(failures: V2Failure[]): ConflictRecord[] {
  return failures.map((f, i) => {
    let resource = humanCheck(f.check);
    for (const [re, take] of RESOURCE_PATTERNS) {
      const m = f.message.match(re);
      if (m) {
        resource = take(m);
        break;
      }
    }
    return { id: `${f.check}-${i}`, check: f.check, resource, message: f.message };
  });
}

/* ------------------------------------------------------------ stage ribbon */

/** Which of the five workspace stages the run has reached. Derived from the
    stages the backend reported — not from how far the user has clicked. */
export function activeStep(
  status: string | null,
  stages: V2Stage[],
  building: boolean,
): number {
  if (!status) return 0;
  if (status === "needs-clarification") return 0;
  const reached = new Set(stages.map((s) => s.stage));
  if (building || reached.has("emulate")) return 4;
  if (reached.has("generate") || reached.has("compile") || reached.has("firmware")) return 3;
  if (reached.has("resource")) return 2;
  if (reached.has("compose")) return 1;
  return 0;
}
