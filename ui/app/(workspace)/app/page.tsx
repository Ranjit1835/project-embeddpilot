"use client";

/* The V2 workspace: one screen, conversation on the left, the generated repo on
   the right. Replaces the wizard-and-bay-tabs layout engineers called clumsy —
   and the specific failure that answering a question felt like starting over,
   because the thread now IS the context.

   THE HONESTY CONTRACT THIS FILE IMPLEMENTS
   -----------------------------------------
   * `extraction_failed` is shown LOUDLY. It means the model never read the
     requirement, so the questions are the whole list rather than the gaps —
     which is indistinguishable from the product being obtuse unless we say so.
   * A run always ends somewhere unmissable: building → completed / blocked /
     did-not-work. Verdicts are the backend's; an unrecognised status is echoed,
     never smoothed into a familiar one.
   * `verdict_note` ("NOT evidence it works on physical hardware") is printed
     whenever the run carried one.
   * Backend unreachable says so. Nothing is shown in its place. */

import { useCallback, useEffect, useRef, useState } from "react";
import { Conversation, type Turn } from "../../../components/workspace/Conversation";
import { CheckStrip } from "../../../components/workspace/CheckStrip";
import { RepoPane } from "../../../components/workspace/RepoPane";
import {
  analyze,
  errorText,
  pollJob,
  requirementFromFile,
  startBuild,
} from "../../../lib/v2-api";
import type { AnalyzeResponse, BuildResult, V2Question } from "../../../lib/v2-types";
import { railFrom } from "../../../lib/v2-view";

type Phase = "idle" | "analysing" | "asking" | "ready" | "building" | "done";

const EXAMPLES = [
  "Read the BMP180 over I2C at address 0x77 and print the raw temperature over UART.",
  "On a Nucleo-F411RE with an STM32F411RET6, read the BMP180 over I2C at 0x77. When the raw reading is above 18500, turn on the relay on PB5. Sample every 500 ms, retry on a failed read, produce a cmake project.",
];

export default function Workspace() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [requirement, setRequirement] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<V2Question[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<BuildResult | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [buildErr, setBuildErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"chat" | "repo">("chat");
  const cancel = useRef<(() => void) | null>(null);
  useEffect(() => () => cancel.current?.(), []);

  const say = (text: string, tone?: Turn extends { tone?: infer T } ? T : never) =>
    setTurns((t) => [...t, { kind: "system", text, tone } as Turn]);

  const applyAnalysis = useCallback((res: AnalyzeResponse) => {
    if (res.extraction_failed) {
      say(
        `The requirement was NOT read — every question below is being asked blind.\n${res.extraction_failed}`,
        "bad" as never,
      );
    }
    const blocking = res.questions.filter((q) => q.blocking);
    setOpen(res.questions);
    if (res.questions.length) {
      setTurns((t) => [
        ...t,
        { kind: "questions", questions: res.questions, answered: {} },
      ]);
    }
    if (!blocking.length) {
      setPhase("ready");
      say(
        res.failures.length
          ? `The spec is complete, but the composition has ${res.failures.length} conflict(s): ${res.failures
              .map((f) => f.message)
              .join("; ")}`
          : "The spec is complete. Build it when you're ready.",
        (res.failures.length ? "warn" : "good") as never,
      );
    } else {
      setPhase("asking");
    }
  }, []);

  const runAnalyze = useCallback(
    async (text: string, acc: Record<string, string>) => {
      setPhase("analysing");
      setPending("reading the requirement…");
      try {
        const res = await analyze(text, acc);
        applyAnalysis(res);
      } catch (e) {
        say(errorText(e), "bad" as never);
        setPhase("idle");
      } finally {
        setPending(null);
      }
    },
    [applyAnalysis],
  );

  const send = useCallback(() => {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    if (phase === "asking" && open.length) {
      // an answer applies to the first still-unanswered question in the thread
      const q = open.find((x) => !answers[x.id]);
      if (q) {
        const next = { ...answers, [q.id]: text };
        setAnswers(next);
        setTurns((t) => [...t, { kind: "you", text }]);
        setTurns((t) =>
          t.map((x) =>
            x.kind === "questions" ? { ...x, answered: next } : x,
          ),
        );
        void runAnalyze(requirement, next);
        return;
      }
    }
    setRequirement(text);
    setTurns((t) => [...t, { kind: "you", text }]);
    void runAnalyze(text, {});
  }, [draft, phase, open, answers, requirement, runAnalyze]);

  const build = useCallback(async () => {
    setPhase("building");
    setBuildErr(null);
    setResult(null);
    setTab("repo");
    say("generating the repo, cross-compiling it and running it under emulation…");
    try {
      const id = await startBuild(requirement, answers);
      setJobId(id);
      cancel.current?.();
      cancel.current = pollJob(
        id,
        (snap) => {
          if (snap.status === "done") {
            setResult(snap.result);
            setPhase("done");
            const r = snap.result;
            if (r) {
              const ok = r.status === "working-emulated";
              say(
                `${r.status.replace(/[-_]/g, " ")}${
                  r.verdict_note ? `\n${r.verdict_note}` : ""
                }`,
                (ok ? "good" : "warn") as never,
              );
            }
          } else if (snap.status === "error") {
            setBuildErr(snap.error ?? "the build failed");
            setPhase("done");
          }
        },
        (err) => {
          setBuildErr(errorText(err));
          setPhase("done");
        },
      );
    } catch (e) {
      setBuildErr(errorText(e));
      setPhase("done");
    }
  }, [requirement, answers]);

  const upload = async (f: File) => {
    setPending(`reading ${f.name}…`);
    try {
      const r = await requirementFromFile(f);
      setDraft((d) => (d ? `${d}\n\n${r.text}` : r.text));
      say(
        `read ${r.filename} — ${r.chars} characters${
          r.pages ? ` from ${r.pages} pages` : ""
        }. Check it in the box before sending; extraction can be lossy.`,
      );
      // An image was READ BY A MODEL, not parsed. Restate the backend's warning
      // verbatim: a confidently misread 0x77 looks exactly like a correct one,
      // and every check downstream would then pass against the wrong address.
      if (r.transcription_warning) say(r.transcription_warning, "warn" as never);
    } catch (e) {
      say(errorText(e), "bad" as never);
    } finally {
      setPending(null);
    }
  };

  const files = result?.files;
  const banner = runBanner(phase, result, buildErr);

  return (
    <div className="flex h-screen flex-col bg-bg">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-line px-4 py-2.5">
        <div className="flex items-baseline gap-3">
          <a href="/" className="text-[13px] font-bold tracking-tight text-ink">
            Embedd<span className="text-accent">Pilot</span>
          </a>
          <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint">
            requirement → verified application
          </span>
        </div>
        <nav className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-faint">
          <a href="/app/settings" className="hover:text-accent">settings</a>
          <a href="/driver" className="hover:text-accent">driver only</a>
        </nav>
      </header>

      {banner}
      {result && (
        <CheckStrip items={railFrom(result.checks, result.stages, result.failures)} />
      )}

      {/* one screen: conversation and repo side by side */}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <section
          className={`flex min-h-0 min-w-0 flex-col md:flex-1 md:border-r md:border-line ${
            tab === "chat" ? "flex-1" : "hidden md:flex"
          }`}
        >
          <Conversation turns={turns} pending={pending} />

          <div className="shrink-0 border-t border-line p-3">
            {turns.length === 0 && (
              <div className="mb-2 flex flex-col gap-1">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    onClick={() => setDraft(ex)}
                    className="truncate rounded border border-line px-2 py-1 text-left font-mono text-[10.5px] text-ink-faint transition-colors hover:border-accent-dim hover:text-ink"
                  >
                    {ex}
                  </button>
                ))}
              </div>
            )}
            <div className="flex items-end gap-2">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
                }}
                rows={3}
                placeholder={
                  phase === "asking"
                    ? "your answer — in your words"
                    : "describe the system you want…"
                }
                className="min-h-[64px] flex-1 resize-none rounded border border-line bg-panel p-2.5 font-mono text-[12px] leading-relaxed text-ink outline-none placeholder:text-ink-faint focus:border-accent-dim"
              />
              <div className="flex flex-col gap-1.5">
                <label className="cursor-pointer rounded border border-line px-2 py-1 text-center font-mono text-[10px] uppercase text-ink-faint hover:text-ink">
                  file
                  <input
                    type="file"
                    accept=".txt,.md,.rst,.log,.pdf,.docx"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      e.target.value = "";
                      if (f) void upload(f);
                    }}
                  />
                </label>
                <button
                  type="button"
                  onClick={send}
                  disabled={!draft.trim() || phase === "analysing"}
                  className="rounded border border-accent-dim px-2 py-1 font-mono text-[10px] uppercase text-accent transition-colors hover:bg-accent/10 disabled:border-line disabled:text-ink-faint"
                >
                  send
                </button>
              </div>
            </div>
            {phase === "ready" && (
              <button
                type="button"
                onClick={build}
                className="mt-2 w-full rounded border border-accent-dim bg-accent/5 py-2 font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-accent transition-colors hover:bg-accent/10"
              >
                build &amp; prove ▸
              </button>
            )}
          </div>
        </section>

        <section
          className={`flex min-h-0 min-w-0 flex-col md:flex-1 ${
            tab === "repo" ? "flex-1" : "hidden md:flex"
          }`}
        >
          <RepoPane files={files} jobId={jobId} building={phase === "building"} />
        </section>
      </div>

      {/* mobile: the two panes are one screen conceptually, two tabs in practice */}
      <div className="flex shrink-0 border-t border-line md:hidden">
        {(["chat", "repo"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`flex-1 py-2 font-mono text-[10px] uppercase tracking-[0.16em] ${
              tab === t ? "bg-accent/10 text-accent" : "text-ink-faint"
            }`}
          >
            {t}
            {t === "repo" && files ? ` · ${Object.keys(files).length}` : ""}
          </button>
        ))}
      </div>
    </div>
  );
}

/* A run must resolve somewhere it cannot be missed — the engineers' report was
   that they could not tell whether anything had happened. */
function runBanner(phase: Phase, result: BuildResult | null, err: string | null) {
  if (phase === "building")
    return (
      <div className="flex shrink-0 items-center gap-2 border-b border-accent-dim/40 bg-accent/5 px-4 py-1.5">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
        <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-accent">
          building — generate → compile → emulate
        </span>
      </div>
    );
  if (err)
    return (
      <div className="shrink-0 border-b border-red/50 bg-red/10 px-4 py-1.5">
        <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-red">
          ✕ build failed
        </span>
        <span className="ml-2 font-mono text-[10px] text-ink-faint">{err}</span>
      </div>
    );
  if (!result) return null;

  const ok = result.status === "working-emulated";
  const blocked =
    result.status.startsWith("blocked") || result.status === "needs-clarification";
  return (
    <div
      className={`shrink-0 border-b px-4 py-1.5 ${
        ok
          ? "border-accent-dim/50 bg-accent/5"
          : blocked
            ? "border-amber/50 bg-amber/10"
            : "border-red/50 bg-red/10"
      }`}
    >
      <span
        className={`font-mono text-[11px] font-bold uppercase tracking-[0.14em] ${
          ok ? "text-accent" : blocked ? "text-amber" : "text-red"
        }`}
      >
        {ok ? "✓ completed" : blocked ? "⚠ blocked" : "✕ did not work"}
      </span>
      <span className="ml-2 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-dim">
        {result.status.replace(/[-_]/g, " ")}
      </span>
      {result.verdict_note && (
        <span className="ml-2 font-mono text-[10px] text-ink-faint">
          {result.verdict_note}
        </span>
      )}
    </div>
  );
}
