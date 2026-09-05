"use client";

/* The V2 workspace. The BOARD is the screen — not a file tree, not a chat rail.
   Left bay is the composed system rendered as copper; right bays are the
   instruments reading it. Every lamp on this screen is lit by a value the
   pipeline returned.

   THE HONESTY CONTRACT THIS FILE IMPLEMENTS
   -----------------------------------------
   * No verdict the backend did not return. `verdictFor` is a total map over
     backend status strings; an unrecognised status is echoed, never smoothed
     into a familiar one, and `verdict_note` is printed only when the run
     carried one.
   * The four check states stay four. `not_applicable` ("nothing to check") and
     `skipped` ("could not check") get their own lamp, glyph and colour — see
     RAIL_STYLE — because rendering either as a green tick would convert an open
     question into evidence.
   * Backend down says backend down. There is no silent fallback to fixtures;
     demo mode is a switch the user throws, and while it is on the chassis wears
     a hazard banner.
   * Nothing is "working" while it is still running. A build in flight shows a
     running lamp on the BUILD row only — the checks it has not reached keep
     whatever state the last real report gave them. */

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { BoardView } from "../../components/resource-map/BoardView";
import { ErrorPlate, Intake } from "../../components/resource-map/Intake";
import {
  Bay,
  GLIDE,
  Led,
  ModeSwitch,
  Rule,
  SNAP,
  Screws,
  StepRibbon,
  type LedTone,
} from "../../components/resource-map/chrome";
import {
  DEMO_ANALYZE,
  DEMO_BUILD,
  DEMO_THRESHOLD_C,
  DEMO_TRACE,
  DEMO_UART,
  type DemoState,
} from "../../lib/resource-map-mock";
import { analyze, errorText, pollJob, startBuild } from "../../lib/v2-api";
import type {
  AnalyzeResponse,
  BuildResult,
  ConsoleLine,
  LineTone,
  V2Stage,
} from "../../lib/v2-types";
import {
  activeStep,
  boardFrom,
  conflictsFrom,
  railFrom,
  targetFrom,
  verdictFor,
  type RailItem,
  type RailState,
} from "../../lib/v2-view";

const STAGES = ["requirements", "devices", "resource map", "code", "run"];

type Source = "live" | "demo";
type BayKey = "stages" | "conflicts" | "run";

/* --- the visual vocabulary for check state -------------------------------

   Four backend states plus two the UI owns. Each row differs in LAMP, GLYPH and
   INK, so none of them can be mistaken for another at a glance:

     pass            green  ✓   "checked, no findings"
     fail            red    ✕   a conflict was reported
     not_applicable  cyan   –   there was nothing to check
     skipped         amber  ⊘   the check could not run — still unknown
     running         green  ◌   (breathing lamp) in flight right now
     pending         off    ○   not reached
*/
const RAIL_STYLE: Record<
  RailState,
  { tone: LedTone; mark: string; ink: string; breathe?: boolean }
> = {
  pass: { tone: "green", mark: "✓", ink: "text-accent" },
  fail: { tone: "red", mark: "✕", ink: "text-red" },
  not_applicable: { tone: "cyan", mark: "–", ink: "text-ink-dim" },
  skipped: { tone: "amber", mark: "⊘", ink: "text-amber" },
  running: { tone: "green", mark: "◌", ink: "text-accent-dim", breathe: true },
  pending: { tone: "off", mark: "○", ink: "text-ink-faint" },
};

const STAGE_STYLE: Record<string, { tone: LedTone; ink: string }> = {
  pass: { tone: "green", ink: "text-accent" },
  fail: { tone: "red", ink: "text-red" },
  blocked: { tone: "red", ink: "text-red" },
  skipped: { tone: "amber", ink: "text-amber" },
  not_applicable: { tone: "cyan", ink: "text-ink-dim" },
};

const LINE_CLASS: Record<LineTone, string> = {
  dim: "text-ink-faint",
  ink: "text-ink",
  good: "text-accent",
  warn: "text-amber",
  bad: "text-red",
};

interface BuildRun {
  jobId: string | null;
  running: boolean;
  result: BuildResult | null;
  error: string | null;
  startedAt: number;
  /** true when this "run" is the recorded fixture, not a live job */
  recorded: boolean;
}

export default function ResourceMapPage() {
  const [source, setSource] = useState<Source>("live");
  const [demoState, setDemoState] = useState<DemoState>("conflict");

  const [requirement, setRequirement] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  /* Bumped on every accepted analyze. Used as the Intake's key so the guided
     walker always restarts at question 1 of the set it is now showing. Keying
     on the question ids is NOT enough: a round can legitimately return the same
     ids (the same fields are still unanswered), and an unchanged key strands
     the cursor on the previous round's last question with no "next". */
  const [analyzeSeq, setAnalyzeSeq] = useState(0);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [intakeOpen, setIntakeOpen] = useState(true);

  const [build, setBuild] = useState<BuildRun | null>(null);
  const [bay, setBay] = useState<BayKey>("stages");
  const [now, setNow] = useState(Date.now());
  const cancelPoll = useRef<(() => void) | null>(null);

  const demo = source === "demo";

  /* -- analyze ----------------------------------------------------------- */

  const runAnalyze = useCallback(
    async (text: string, acc: Record<string, string>) => {
      setAnalyzing(true);
      setAnalyzeError(null);
      try {
        const res = await analyze(text, acc);
        setAnalysis(res);
        setAnswers(acc);
        setAnalyzeSeq((n) => n + 1);
        // the loop only closes when nothing blocking is left
        const blocking = res.questions.filter((q) => q.blocking).length;
        setIntakeOpen(blocking > 0);
        if (blocking === 0) setBay(res.failures.length ? "conflicts" : "stages");
      } catch (e) {
        setAnalyzeError(errorText(e));
      } finally {
        setAnalyzing(false);
      }
    },
    [],
  );

  const onAnalyze = useCallback(() => {
    setBuild(null);
    void runAnalyze(requirement, {});
  }, [requirement, runAnalyze]);

  const onAnswer = useCallback(
    (add: Record<string, string>) => {
      void runAnalyze(requirement, { ...answers, ...add });
    },
    [requirement, answers, runAnalyze],
  );

  /* -- build ------------------------------------------------------------- */

  useEffect(() => () => cancelPoll.current?.(), []);

  // an honest elapsed-time readout while a job is in flight
  useEffect(() => {
    if (!build?.running) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [build?.running]);

  const onBuild = useCallback(async () => {
    setBay("run");
    if (demo) {
      setBuild({
        jobId: null,
        running: false,
        result: DEMO_BUILD,
        error: null,
        startedAt: Date.now(),
        recorded: true,
      });
      return;
    }
    setBuild({
      jobId: null,
      running: true,
      result: null,
      error: null,
      startedAt: Date.now(),
      recorded: false,
    });
    try {
      const jobId = await startBuild(requirement, answers);
      setBuild((b) => (b ? { ...b, jobId } : b));
      cancelPoll.current?.();
      cancelPoll.current = pollJob(
        jobId,
        (snap) => {
          if (snap.status === "done")
            setBuild((b) =>
              b ? { ...b, running: false, result: snap.result } : b,
            );
          else if (snap.status === "error")
            setBuild((b) =>
              b
                ? { ...b, running: false, error: snap.error ?? "job failed" }
                : b,
            );
        },
        (err) =>
          setBuild((b) => (b ? { ...b, running: false, error: err.message } : b)),
      );
    } catch (e) {
      setBuild((b) =>
        b ? { ...b, running: false, error: errorText(e) } : b,
      );
    }
  }, [demo, requirement, answers]);

  /* -- what is actually on screen ---------------------------------------- */

  const current: AnalyzeResponse | null = demo ? DEMO_ANALYZE[demoState] : analysis;
  const result = build?.result ?? null;

  /* A finished build is the newer and fuller report, so it supersedes the
     analyze snapshot for checks/stages/failures. The resource map and spec only
     ever come from analyze — build does not return them. */
  const status = result?.status ?? current?.status ?? null;
  const stages: V2Stage[] = result?.stages ?? current?.stages ?? [];
  const checks = result?.checks ?? current?.checks ?? {};
  const failures = result?.failures ?? current?.failures ?? [];
  const devices = result?.devices ?? current?.devices ?? [];

  const board = boardFrom(
    devices,
    current?.resource_map ?? null,
    failures,
    current?.spec,
    targetFrom(current?.spec),
  );

  const conflicts = conflictsFrom(failures);
  const blockingQuestions = current?.questions.filter((q) => q.blocking).length ?? 0;

  const rail: RailItem[] = railFrom(checks, stages, failures);
  if (build?.running)
    rail.unshift({
      id: "build",
      label: "build",
      state: "running",
      note: "generate → compile → emulate",
    });

  const verdict = build?.running
    ? { label: "BUILD RUNNING", tone: "idle" as const }
    : verdictFor(status, failures, blockingQuestions);

  const step = activeStep(status, stages, Boolean(build?.running));
  const canBuild =
    !!current &&
    blockingQuestions === 0 &&
    !build?.running &&
    status !== "blocked-resource-conflict";
  const buildBlockedReason = !current
    ? "analyse a requirement first"
    : blockingQuestions > 0
      ? `${blockingQuestions} blocking question(s) still unanswered`
      : status === "blocked-resource-conflict"
        ? "resolve the reported conflict first — the pipeline refuses to emulate a system whose resources collide"
        : "";

  /* -------------------------------------------------------------- render */

  return (
    <div className="ins-room relative flex min-h-screen flex-col">
      {/* ------------------------------------------------ chassis header */}
      <header className="ins-chassis relative flex items-center justify-between gap-6 border-b border-line px-5 py-2.5">
        <Screws />
        <div className="flex items-baseline gap-3">
          <span className="text-[13px] font-bold uppercase tracking-[0.3em] text-ink">
            Embedd<span className="text-accent">Pilot</span>
          </span>
          <span className="ins-mono text-[10px] uppercase tracking-[0.18em] text-ink-faint">
            v2 · requirement → verified application
          </span>
        </div>

        <StepRibbon steps={STAGES} active={step} />

        <ModeSwitch<Source>
          ariaLabel="Data source"
          value={source}
          onChange={setSource}
          options={[
            { value: "live", label: "live api", tone: "green" },
            { value: "demo", label: "demo fixture", tone: "amber" },
          ]}
        />
      </header>

      {/* ------------------------------------------------- provenance strip */}
      <div
        className={`flex flex-wrap items-center gap-x-4 gap-y-1 border-b px-4 py-1.5 ${
          demo ? "border-amber/40 bg-amber/5" : "border-line"
        }`}
      >
        {demo ? (
          <>
            <span className="ins-hazard h-[10px] w-[54px] shrink-0" aria-hidden />
            <span className="ins-mono text-[10px] font-bold uppercase tracking-[0.2em] text-amber">
              demo — recorded fixture data, not a live run
            </span>
            <span className="ins-mono text-[10px] text-ink-faint">
              nothing here was produced by the pipeline just now
            </span>
            <ModeSwitch<DemoState>
              ariaLabel="Demo board state"
              value={demoState}
              onChange={(v) => {
                setDemoState(v);
                setBuild(null);
                setBay(v === "conflict" ? "conflicts" : "stages");
              }}
              options={[
                { value: "conflict", label: "as designed", tone: "red" },
                { value: "resolved", label: "after fix", tone: "green" },
              ]}
            />
          </>
        ) : (
          <>
            <Led tone={analysis ? "green" : "off"} breathe={analyzing} />
            <span className="ins-mono text-[10px] uppercase tracking-[0.18em] text-ink-dim">
              live · /api/v2 · {analysis ? "reporting a real run" : "no run yet"}
            </span>
            {requirement && (
              <button
                type="button"
                onClick={() => setIntakeOpen(true)}
                className="ins-mono max-w-[46ch] truncate text-left text-[10px] text-ink-faint underline decoration-line underline-offset-2 hover:text-ink-dim"
                title={requirement}
              >
                “{requirement}”
              </button>
            )}
          </>
        )}

        <div className="ml-auto flex items-center gap-2">
          {!demo && (
            <button
              type="button"
              onClick={() => setIntakeOpen(true)}
              className="ins-key border border-line px-2.5 py-1 text-[10px] uppercase tracking-[0.18em] text-ink-dim hover:text-ink"
            >
              {analysis ? "revise requirement" : "new requirement"}
            </button>
          )}
          <button
            type="button"
            onClick={onBuild}
            disabled={!canBuild}
            title={buildBlockedReason || undefined}
            className="ins-key border border-accent-dim px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.2em] text-accent transition-colors hover:bg-accent/10 disabled:cursor-not-allowed disabled:border-line disabled:text-ink-faint"
          >
            {build?.running ? "building…" : demo ? "show recorded build ▸" : "build & prove ▸"}
          </button>
        </div>
      </div>

      {/* --------------------------------------------- intake, or the bench */}
      {!demo && intakeOpen ? (
        <Intake
          key={analyzeSeq}
          requirement={requirement}
          onRequirementChange={setRequirement}
          questions={analysis?.questions ?? []}
          answers={answers}
          busy={analyzing}
          error={analyzeError}
          phase={
            analysis && analysis.questions.length > 0 ? "questions" : "requirement"
          }
          onAnalyze={onAnalyze}
          onAnswer={onAnswer}
          onDismiss={analysis ? () => setIntakeOpen(false) : null}
          onUseDemo={() => setSource("demo")}
        />
      ) : (
      <main className="grid min-h-0 flex-1 gap-3 p-3 lg:grid-cols-[minmax(0,1.55fr)_minmax(360px,0.95fr)]">
        <Bay
          glass
          tone={failures.length ? "alarm" : current ? "accent" : "dim"}
          legend={`target · ${board.target.mcu}`}
          right={
            <span className="ins-mono flex items-center gap-3 text-[10px] uppercase tracking-[0.16em] text-ink-faint">
              {board.target.output && (
                <span>
                  output · <span className="text-ink-dim">{board.target.output}</span>
                </span>
              )}
              <span>{board.target.board}</span>
            </span>
          }
          className="min-h-[420px]"
        >
          <BoardView board={board} />
        </Bay>

        <div className="flex min-h-0 flex-col gap-3">
          <Bay
            legend="devices"
            right={<Count n={board.devices.length} />}
            className="max-h-[46%]"
          >
            <div className="min-h-0 overflow-auto">
              {board.devices.length === 0 ? (
                <p className="ins-mono p-3 text-[10.5px] leading-relaxed text-ink-faint">
                  {current
                    ? "the spec has not named a device yet — nothing to compose"
                    : "no run yet"}
                </p>
              ) : (
                <ul className="divide-y divide-line">
                  {board.devices.map((d) => (
                    <li key={d.id} className="flex items-start gap-3 px-3 py-2">
                      <Led tone={d.status === "conflict" ? "red" : "green"} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline gap-2">
                          <span className="text-[12px] font-semibold tracking-wide text-ink">
                            {d.name}
                          </span>
                          <span className="ins-mono text-[10px] text-ink-faint">
                            {d.iface}
                            {d.addr ? ` · ${d.addr}` : ""}
                          </span>
                        </div>
                        <p className="truncate text-[10px] uppercase tracking-[0.14em] text-ink-faint">
                          {d.role}
                        </p>
                        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                          {d.facts.map((f) => (
                            <span
                              key={f}
                              className={`ins-mono text-[10px] ${
                                d.status === "conflict" ? "text-red" : "text-accent-dim"
                              }`}
                            >
                              {f}
                            </span>
                          ))}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Bay>

          <Bay
            tone={bay === "conflicts" && conflicts.length ? "alarm" : "dim"}
            legend={
              <Tabs
                value={bay}
                onChange={setBay}
                items={[
                  { key: "stages", label: "stages", badge: stages.length },
                  { key: "conflicts", label: "conflicts", badge: conflicts.length, alarm: conflicts.length > 0 },
                  { key: "run", label: "run", badge: result ? 1 : 0 },
                ]}
              />
            }
            className="min-h-0 flex-1"
          >
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={bay}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={SNAP}
                className="h-full min-h-0 overflow-auto"
              >
                {bay === "stages" && <StagesBay stages={stages} current={current} />}
                {bay === "conflicts" && <ConflictsBay conflicts={conflicts} hasRun={!!current} />}
                {bay === "run" && (
                  <RunBay
                    build={build}
                    demo={demo}
                    now={now}
                    blockedReason={buildBlockedReason}
                  />
                )}
              </motion.div>
            </AnimatePresence>
          </Bay>
        </div>
      </main>
      )}

      {/* live-mode failure surfaces here, never as silent fixture data */}
      {!demo && analyzeError && !intakeOpen && (
        <div className="px-3 pb-2">
          <ErrorPlate text={analyzeError} />
        </div>
      )}

      {/* -------------------------------------------------- verdict rail */}
      <footer className="ins-chassis border-t border-line px-3 py-2">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          {rail.length === 0 ? (
            <span className="ins-mono text-[11px] text-ink-faint">
              ○ no checks have run{" "}
              {current
                ? "— the spec is still incomplete, so nothing was validated"
                : "— nothing has been analysed yet"}
            </span>
          ) : (
            rail.map((c) => {
              const s = RAIL_STYLE[c.state];
              return (
                <div key={c.id} className="flex items-center gap-2">
                  <Led tone={s.tone} breathe={s.breathe} />
                  <span className={`ins-mono text-[11px] ${s.ink}`}>
                    {s.mark} {c.label}
                  </span>
                  <span className="ins-mono max-w-[34ch] truncate text-[10px] text-ink-faint" title={c.note}>
                    {c.note}
                  </span>
                </div>
              );
            })
          )}

          <motion.div
            layout
            transition={GLIDE}
            className={`ml-auto flex items-center gap-2 border px-3 py-1 ${
              verdict.tone === "good"
                ? "ins-glow border-accent-dim text-accent"
                : verdict.tone === "bad"
                  ? "ins-blink border-red/50 text-red"
                  : verdict.tone === "warn"
                    ? "border-amber/50 text-amber"
                    : "border-line text-ink-faint"
            }`}
          >
            <span className="ins-mono text-[11px] font-bold tracking-[0.18em]">
              {verdict.label}
            </span>
          </motion.div>
        </div>

        {/* the sentence that says emulation is not hardware. Printed only when
            the run returned one — never composed here. */}
        {result?.verdict_note && (
          <p className="ins-mono mt-1.5 text-[10px] leading-relaxed text-ink-dim">
            <span className="text-accent-dim">verdict note ·</span>{" "}
            {result.verdict_note}
            {build?.recorded && (
              <span className="text-amber"> (recorded fixture run)</span>
            )}
          </p>
        )}
        {result && !result.verdict_note && (
          <p className="ins-mono mt-1.5 text-[10px] text-ink-faint">
            the run returned no verdict note — it did not reach a working
            verdict, so there is nothing to qualify
          </p>
        )}
      </footer>

    </div>
  );
}

/* ------------------------------------------------------------ sub-bays */

function Count({ n }: { n: number }) {
  return (
    <span className="ins-mono text-[10px] tracking-[0.16em] text-ink-faint">
      {String(n).padStart(2, "0")}
    </span>
  );
}

function Tabs<T extends string>({
  value,
  onChange,
  items,
}: {
  value: T;
  onChange: (v: T) => void;
  items: { key: T; label: string; badge: number; alarm?: boolean }[];
}) {
  return (
    <span className="flex items-center gap-1" role="tablist">
      {items.map((it) => {
        const on = it.key === value;
        return (
          <button
            key={it.key}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(it.key)}
            className={`px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.2em] transition-colors ${
              on
                ? it.alarm
                  ? "text-red"
                  : "text-accent"
                : "text-ink-faint hover:text-ink-dim"
            }`}
          >
            {it.label}
            {it.badge > 0 && (
              <span className={`ml-1 ${it.alarm ? "text-red" : "text-ink-faint"}`}>
                {it.badge}
              </span>
            )}
          </button>
        );
      })}
    </span>
  );
}

function StagesBay({
  stages,
  current,
}: {
  stages: V2Stage[];
  current: AnalyzeResponse | null;
}) {
  if (!stages.length)
    return (
      <p className="ins-mono p-3 text-[10.5px] text-ink-faint">
        {current
          ? "the pipeline reported no stages for this run"
          : "no run yet — analyse a requirement to see the pipeline's own stage report"}
      </p>
    );
  return (
    <ul className="divide-y divide-line">
      {stages.map((s, i) => {
        const style = STAGE_STYLE[s.state] ?? { tone: "off" as LedTone, ink: "text-ink-faint" };
        return (
          <li key={`${s.stage}-${i}`} className="flex items-start gap-3 px-3 py-2">
            <span className="mt-[3px]">
              <Led tone={style.tone} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[12px] font-semibold uppercase tracking-[0.16em] text-ink">
                  {s.stage}
                </span>
                <span className={`ins-mono text-[10px] uppercase tracking-[0.14em] ${style.ink}`}>
                  {s.state.replace(/_/g, " ")}
                </span>
              </div>
              {s.detail && (
                <p className="ins-mono mt-0.5 text-[10px] leading-relaxed text-ink-dim">
                  {s.detail}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function ConflictsBay({
  conflicts,
  hasRun,
}: {
  conflicts: ReturnType<typeof conflictsFrom>;
  hasRun: boolean;
}) {
  if (!conflicts.length)
    return (
      <p className="ins-mono p-3 text-[10.5px] leading-relaxed text-ink-faint">
        {hasRun
          ? "no resource conflicts were reported for this composition. That is the cross-check's finding, not a claim that every pin can carry its function — the alternate-function table needed for that is not available and is not guessed."
          : "no run yet"}
      </p>
    );

  return (
    <div className="flex h-full flex-col">
      <div className="ins-hazard h-[6px] shrink-0" aria-hidden />
      <ul className="flex min-h-0 flex-1 flex-col divide-y divide-line overflow-auto">
        {conflicts.map((c) => (
          <li key={c.id} className="flex flex-col gap-1.5 px-3 py-2.5">
            <div className="flex items-baseline gap-2">
              <span className="ins-blink text-red">⚠</span>
              <span className="text-[13px] font-bold tracking-wide text-red">
                {c.resource}
              </span>
              <span className="ins-mono ml-auto text-[10px] text-ink-faint">
                {c.check}
              </span>
            </div>
            {/* the backend's own words, including its own remedy. This screen
                does not propose a fix: the pipeline explicitly refuses to
                reassign a pin behind the user's back, and a suggestion invented
                here would be that same lie one layer up. */}
            <p className="ins-mono text-[10.5px] leading-relaxed text-ink-dim">
              {c.message}
            </p>
          </li>
        ))}
      </ul>
      <div className="shrink-0 border-t border-line px-3 py-2">
        <p className="ins-mono text-[10px] leading-relaxed text-ink-faint">
          Resolving this is a decision, not an autofix — revise the requirement
          or your answers and re-analyse.
        </p>
      </div>
    </div>
  );
}

function RunBay({
  build,
  demo,
  now,
  blockedReason,
}: {
  build: BuildRun | null;
  demo: boolean;
  now: number;
  blockedReason: string;
}) {
  if (!build)
    return (
      <p className="ins-mono p-3 text-[10.5px] leading-relaxed text-ink-faint">
        no build has been run.{" "}
        {blockedReason
          ? `“build & prove” is disabled: ${blockedReason}.`
          : "press “build & prove” to generate the firmware, cross-compile it and run it under emulation."}
      </p>
    );

  if (build.running)
    return (
      <div className="flex flex-col gap-2 p-3">
        <div className="flex items-center gap-2">
          <Led tone="green" breathe />
          <span className="ins-mono text-[11px] uppercase tracking-[0.18em] text-accent">
            build running · {((now - build.startedAt) / 1000).toFixed(1)}s
          </span>
        </div>
        <p className="ins-mono text-[10px] leading-relaxed text-ink-faint">
          job {build.jobId ?? "…"} · generate → cross-compile → emulate.
        </p>
        <Rule />
        <p className="ins-mono text-[10px] leading-relaxed text-ink-faint">
          The V2 build job reports its stages once, when the pipeline returns —
          it emits no intermediate progress. Rather than animate stages that have
          not been reported, this bay shows only what is true right now: the job
          is in flight.
        </p>
      </div>
    );

  if (build.error)
    return (
      <div className="p-3">
        <ErrorPlate text={build.error} />
      </div>
    );

  const r = build.result;
  if (!r) return null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {demo && build.recorded && (
        <>
          <Scope trace={DEMO_TRACE} threshold={DEMO_THRESHOLD_C} />
          <Rule />
        </>
      )}

      <div className="flex items-center justify-between gap-3 px-3 py-2">
        <span className="ins-mono text-[10px] uppercase tracking-[0.16em] text-ink-dim">
          firmware origin ·{" "}
          <span className={r.firmware_origin === "generated" ? "text-accent" : "text-amber"}>
            {r.firmware_origin ?? "none — no firmware was produced"}
          </span>
        </span>
        <span className="ins-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint">
          {r.status.replace(/[-_]/g, " ")}
        </span>
      </div>
      <Rule />

      <div className="ins-face min-h-0 flex-1 overflow-auto p-2.5">
        {demo && build.recorded
          ? DEMO_UART.map((l, i) => <ConsoleRow key={i} line={l} index={i} />)
          : reportLines(r).map((l, i) => <ConsoleRow key={i} line={l} index={i} />)}
        <span className="ins-caret ins-mono text-[10.5px] text-accent">▌</span>
      </div>
    </div>
  );
}

/** A live build returns stages, notes and failures — not a UART capture. So the
    live console prints exactly those, and never a fabricated transcript. */
function reportLines(r: BuildResult): ConsoleLine[] {
  const out: ConsoleLine[] = [];
  out.push({ t: "", text: "── pipeline ───────────────────────────", tone: "dim" });
  const stageTone: Record<string, LineTone> = {
    pass: "good",
    skipped: "warn",
    not_applicable: "dim",
    fail: "bad",
    blocked: "bad",
  };
  for (const s of r.stages)
    out.push({
      t: "",
      text: `${s.stage.padEnd(10)} ${s.state.toUpperCase()}${s.detail ? `  ${s.detail}` : ""}`,
      tone: stageTone[s.state] ?? "ink",
    });
  if (Object.keys(r.checks).length) {
    out.push({ t: "", text: "── checks ─────────────────────────────", tone: "dim" });
    for (const [k, v] of Object.entries(r.checks))
      out.push({
        t: "",
        text: `${k.padEnd(20)} ${v.toUpperCase()}`,
        tone: v === "pass" ? "good" : v === "fail" ? "bad" : "warn",
      });
  }
  if (r.failures.length) {
    out.push({ t: "", text: "── failures ───────────────────────────", tone: "dim" });
    for (const f of r.failures) out.push({ t: "", text: f.message, tone: "bad" });
  }
  if (r.notes.length) {
    out.push({ t: "", text: "── notes ──────────────────────────────", tone: "dim" });
    for (const n of r.notes) out.push({ t: "", text: n, tone: "ink" });
  }
  if (r.derivation_notes?.length) {
    out.push({ t: "", text: "── read plan ──────────────────────────", tone: "dim" });
    for (const n of r.derivation_notes) out.push({ t: "", text: n, tone: "ink" });
  }
  return out;
}

function ConsoleRow({ line, index }: { line: ConsoleLine; index: number }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: Math.min(index * 0.03, 0.9), duration: 0.2 }}
      className="flex gap-2"
    >
      {line.t && <span className="ins-mono text-[10px] text-ink-faint">{line.t}</span>}
      <span className={`ins-mono whitespace-pre-wrap text-[10.5px] ${LINE_CLASS[line.tone]}`}>
        {line.text}
      </span>
    </motion.div>
  );
}

/** Temperature trace with the threshold that trips the relay. Demo only — a
    live V2 build returns no sample stream, so there is nothing to plot. */
function Scope({ trace, threshold }: { trace: number[]; threshold: number }) {
  const W = 320;
  const H = 64;
  const lo = 22;
  const hi = 33;
  const x = (i: number) => (i / (trace.length - 1)) * W;
  const y = (t: number) => H - ((t - lo) / (hi - lo)) * H;
  const d = trace
    .map((t, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(t).toFixed(1)}`)
    .join(" ");
  const trip = trace.findIndex((t) => t > threshold);

  return (
    <div className="relative px-2.5 pt-2">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-[64px] w-full"
        role="img"
        aria-label={`Recorded temperature trace crossing the ${threshold} degree threshold`}
      >
        <line
          x1={0}
          x2={W}
          y1={y(threshold)}
          y2={y(threshold)}
          stroke="#e0a63c"
          strokeWidth={1}
          strokeDasharray="3 3"
          opacity={0.7}
        />
        <motion.path
          d={d}
          fill="none"
          stroke="#3fe081"
          strokeWidth={1.6}
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 1.1, ease: "easeOut" }}
          style={{ filter: "drop-shadow(0 0 4px #3fe081)" }}
        />
        {trip > -1 && <circle cx={x(trip)} cy={y(trace[trip])} r={3} fill="#e0a63c" />}
      </svg>
      <span className="ins-mono absolute right-3 top-2 text-[9px] text-amber">
        {threshold.toFixed(1)} °C
      </span>
    </div>
  );
}
