/* Recorded-demo mode for hosted deployments (no Python backend available).
   Replays REAL captured pipeline runs from demo-data.json — actual extracted
   maps, actual generated files, actual validator reports. Activated only when
   the live API is unreachable; clearly labeled in the UI. */

import rawData from "./demo-data.json";
import type {
  GenerationResult,
  JobEvent,
  RegisterMap,
  Sample,
  ValidationReport,
} from "./types";

interface DemoRun {
  platform: string;
  register_map: RegisterMap;
  result: GenerationResult & { reports: ValidationReport[] };
}

const data = rawData as unknown as {
  samples: Sample[];
  runs: Record<string, DemoRun>;
};

/* --- demo-active store (drives the "recorded case study" banner) --- */

let active = false;
const listeners = new Set<() => void>();

export function markDemo(): void {
  if (!active) {
    active = true;
    listeners.forEach((l) => l());
  }
}

export function subscribeDemoFlag(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export const isDemoActive = () => active;

/* --- recorded data access --- */

export const demoSamples: Sample[] = data.samples;

export function demoRun(id: string): DemoRun {
  return data.runs[id];
}

export function demoRunIdForMap(map: RegisterMap): string {
  const hit = Object.entries(data.runs).find(
    ([, r]) => r.register_map.chip === map.chip,
  );
  return hit ? hit[0] : data.samples[0].id;
}

/* --- replay engine: real reports, staged on a believable timeline --- */

export function playDemoRun(
  id: string,
  onEvent: (e: JobEvent) => void,
): () => void {
  const run = data.runs[id];
  const timers: ReturnType<typeof setTimeout>[] = [];
  // Omit<> does not distribute over the JobEvent union; the cast is safe
  // because every emitted object matches one union member plus ts
  const at = (ms: number, e: object) =>
    timers.push(setTimeout(() => onEvent({ ts: Date.now(), ...e } as JobEvent), ms));

  let t = 300;
  at(t, { type: "route", decision: run.result.decision });
  for (let i = 0; i < run.result.reports.length; i++) {
    t += 700;
    at(t, { type: "attempt_start", attempt: i + 1 });
    t += 1600;
    at(t, { type: "attempt_report", attempt: i + 1, report: run.result.reports[i] });
  }
  t += 500;
  at(t, { type: "job_done", status: "done", error: null });
  return () => timers.forEach(clearTimeout);
}

export function demoResult(id: string): GenerationResult {
  return data.runs[id].result;
}

/** Client-side download for demo results (no backend zip endpoint). */
export function downloadDemoBundle(id: string): void {
  const run = data.runs[id];
  const bundle = {
    files: run.result.files,
    "register-map": run.register_map,
    provenance: {
      status: run.result.status,
      decision: run.result.decision,
      attempts: run.result.attempts,
      provider: run.result.provider,
      note: "recorded pipeline run — see repo for the live stack",
    },
  };
  const blob = new Blob([JSON.stringify(bundle, null, 1)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `embeddpilot_${id}_recorded.json`;
  a.click();
  URL.revokeObjectURL(url);
}
