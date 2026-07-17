import type { GenerationResult, JobEvent, RegisterMap, Sample } from "./types";

/* The Next dev server rewrites /api/* to the FastAPI service (next.config). */

export async function startIngest(form: FormData): Promise<string> {
  const res = await fetch("/api/ingest", { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
  return (await res.json()).job_id;
}

export async function startGenerate(payload: {
  register_map: RegisterMap;
  platform: string;
  conventions?: string;
  max_retries?: number;
  edits?: string[];
}): Promise<string> {
  const res = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
  return (await res.json()).job_id;
}

export interface JobSnapshot {
  id: string;
  kind: string;
  status: "running" | "done" | "error";
  events: JobEvent[];
  result: (GenerationResult & { register_map?: RegisterMap }) | null;
  error: string | null;
}

export async function jobSnapshot(jobId: string): Promise<JobSnapshot> {
  const res = await fetch(`/api/jobs/${jobId}`);
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

/** Subscribe to a job's event feed. SSE first; if the stream stalls or drops
    (proxies can buffer event-streams), falls back to snapshot polling.
    Events are delivered exactly once, in order. */
export function subscribeJob(
  jobId: string,
  onEvent: (e: JobEvent) => void,
): () => void {
  let delivered = 0;
  let done = false;
  let es: EventSource | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let watchdog: ReturnType<typeof setTimeout> | null = null;

  const deliver = (e: JobEvent) => {
    delivered += 1;
    if (e.type === "job_done") done = true;
    onEvent(e);
  };

  const stopAll = () => {
    es?.close();
    if (pollTimer) clearInterval(pollTimer);
    if (watchdog) clearTimeout(watchdog);
  };

  const startPolling = () => {
    es?.close();
    es = null;
    if (pollTimer || done) return;
    pollTimer = setInterval(async () => {
      try {
        const snap = await jobSnapshot(jobId);
        for (const e of snap.events.slice(delivered)) deliver(e);
        if (done && pollTimer) clearInterval(pollTimer);
      } catch {
        /* transient; keep polling */
      }
    }, 1500);
  };

  es = new EventSource(`/api/jobs/${jobId}/events`);
  // if no event (not even the immediate history replay) lands quickly,
  // assume a buffering proxy and switch to polling
  watchdog = setTimeout(() => {
    if (delivered === 0) startPolling();
  }, 3000);
  es.onmessage = (msg) => {
    deliver(JSON.parse(msg.data) as JobEvent);
    if (done) stopAll();
  };
  es.onerror = () => startPolling();

  return stopAll;
}

export async function listSamples(): Promise<Sample[]> {
  const res = await fetch("/api/samples");
  return res.ok ? res.json() : [];
}

export async function getSample(
  id: string,
): Promise<{ register_map: RegisterMap; platform: string; label: string }> {
  const res = await fetch(`/api/samples/${id}`);
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export function downloadUrl(jobId: string): string {
  return `/api/jobs/${jobId}/download`;
}
