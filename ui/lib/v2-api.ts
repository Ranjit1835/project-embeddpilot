/* V2 API client: requirement -> analyze -> build.

   The Next dev server rewrites /api/* to the FastAPI service (next.config.ts).

   HONESTY CONTRACT — this module never falls back to fixtures. If the backend
   is unreachable it throws `BackendUnreachable` and the screen says so; showing
   demo data in place of a failed live call would make a viewer believe they were
   looking at a real run. Demo mode exists (lib/v2-demo.ts) but it is only ever
   entered by an explicit, visible user choice. */

import type { AnalyzeResponse, JobEnvelope } from "./v2-types";

/** The API did not answer at all — no server, wrong port, DNS, offline. */
export class BackendUnreachable extends Error {
  constructor(path: string, cause?: unknown) {
    super(
      `No response from ${path}. The pipeline API is not answering — start it ` +
        `with \`uvicorn api.main:app --port 8000\` (the UI proxies /api to it).`,
    );
    this.name = "BackendUnreachable";
    this.cause = cause;
  }
}

/** The API answered, and its answer was an error. Carries the backend's own
    words: a 503 here means "no LLM provider configured", which is a very
    different problem from "the server is down" and must not read as one. */
export class BackendRefused extends Error {
  constructor(
    readonly httpStatus: number,
    detail: string,
  ) {
    super(detail);
    this.name = "BackendRefused";
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (cause) {
    throw new BackendUnreachable(path, cause);
  }
  if (!res.ok) {
    const payload = (await res.json().catch(() => null)) as
      | { detail?: unknown }
      | null;
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : `${res.status} ${res.statusText}`;
    throw new BackendRefused(res.status, detail);
  }
  return (await res.json()) as T;
}

/** Requirement (+ every answer given so far) -> questions, devices, resource
    map, checks. Fast and synchronous; no toolchain involved.

    `answers` is cumulative on purpose: the backend applies answers to a
    fixpoint, and answering one question can raise new ones (answering "which
    device?" creates the device, which then needs an interface and a role). */
export function analyze(
  requirement: string,
  answers: Record<string, string>,
): Promise<AnalyzeResponse> {
  return postJson<AnalyzeResponse>("/api/v2/analyze", { requirement, answers });
}

/** Kicks off generate + cross-compile + emulate. Returns a job id to poll. */
export async function startBuild(
  requirement: string,
  answers: Record<string, string>,
): Promise<string> {
  const { job_id } = await postJson<{ job_id: string }>("/api/v2/build", {
    requirement,
    answers,
  });
  return job_id;
}

export async function jobSnapshot(jobId: string): Promise<JobEnvelope> {
  let res: Response;
  const path = `/api/jobs/${jobId}`;
  try {
    res = await fetch(path);
  } catch (cause) {
    throw new BackendUnreachable(path, cause);
  }
  if (!res.ok) throw new BackendRefused(res.status, res.statusText);
  return (await res.json()) as JobEnvelope;
}

/** Poll a build job to completion.
 *
 * Deliberately a poll rather than the V1 SSE subscription: `_run_v2_build`
 * emits no intermediate events — it reports its stages once, when the pipeline
 * returns. So there is no live stage feed to subscribe to, and inventing a
 * progress animation for stages the backend has not reported yet would be
 * exactly the kind of "looks like it's working" lie this project exists to
 * avoid. `onSnapshot` fires on every poll so the screen can show honest elapsed
 * time, and any events the job DOES emit are passed through as they land.
 *
 * Returns a cancel function.
 */
export function pollJob(
  jobId: string,
  onSnapshot: (snap: JobEnvelope) => void,
  onError: (err: Error) => void,
  intervalMs = 1200,
): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const tick = async () => {
    if (stopped) return;
    try {
      const snap = await jobSnapshot(jobId);
      if (stopped) return;
      onSnapshot(snap);
      if (snap.status === "done" || snap.status === "error") return;
    } catch (e) {
      if (stopped) return;
      onError(e instanceof Error ? e : new Error(String(e)));
      return;
    }
    timer = setTimeout(tick, intervalMs);
  };

  void tick();
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
  };
}

/** One place that turns any thrown value into a sentence a user can act on. */
export function errorText(e: unknown): string {
  if (e instanceof BackendUnreachable || e instanceof BackendRefused)
    return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}
