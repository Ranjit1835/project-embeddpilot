"use client";

/* REQUIREMENT INTAKE — the clarify-first loop.

   Deliberately NOT a chat rail. A permanent conversation column would make the
   model the product and the board a side panel; here intake is a MODE the bench
   enters, does one job, and leaves. When it is done the board is the screen
   again.

   The loop: requirement -> /api/v2/analyze -> if the spec is ambiguous the
   backend returns questions -> we ask them ONE AT A TIME -> re-analyze with the
   accumulated answers -> repeat until nothing blocking is left. Answering a
   question can raise new ones (naming a device creates a device, which then
   needs an interface and a role), so this is a loop and not a form.

   TWO RULES THIS COMPONENT ENFORCES
   ---------------------------------
   1. No skipping. A blocking question gates the run; there is no path past it.
      "No spec line, no code" is the product, not a speed bump.
   2. No autofill. Every input starts empty, no option is pre-selected, and
      nothing is remembered across a different question. An answer this UI wrote
      would carry provenance "asked" back to the pipeline and be indistinguish-
      able from something the human said — which is precisely the invisible
      failure generation/spec.py exists to prevent. */

import { AnimatePresence, motion } from "framer-motion";
import { useMemo, useState } from "react";
import type { V2Question } from "../../lib/v2-types";
import { Bay, Led, Rule, SNAP, Screws } from "./chrome";

const EXAMPLES = [
  "On a Nucleo-F411RE with an STM32F411RET6, read the BME280 over I2C at " +
    "address 0x76 and drive an SSD1306 OLED over I2C at address 0x3C. Sample " +
    "every 500 ms, print readings over UART, retry on a failed read, and " +
    "produce a cmake project.",
  "Read the BMP180 over I2C at address 0x77 and print the raw temperature " +
    "over UART.",
];

export interface IntakeProps {
  requirement: string;
  onRequirementChange: (v: string) => void;
  questions: V2Question[];
  /** answers already accepted by the backend, for the ledger */
  answers: Record<string, string>;
  busy: boolean;
  error: string | null;
  /** "requirement" until the first analyze lands, then "questions" */
  phase: "requirement" | "questions";
  onAnalyze: () => void;
  onAnswer: (add: Record<string, string>) => void;
  onDismiss: (() => void) | null;
  /** offered only on the error plate — the escape hatch when the API is down */
  onUseDemo: (() => void) | null;
}

export function Intake(props: IntakeProps) {
  /* Rendered in the bench's place rather than over it. An overlay would cover
     the chassis header, and with it the live/demo switch — which is exactly the
     control someone needs when the reason they are stuck on this screen is that
     the backend is not answering. */
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      <div className="mx-auto flex w-full max-w-[880px] flex-1 flex-col gap-3 p-4">
        {props.phase === "requirement" ? (
          <RequirementStep {...props} />
        ) : (
          <QuestionStep {...props} />
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- step one */

function RequirementStep({
  requirement,
  onRequirementChange,
  busy,
  error,
  onAnalyze,
  onDismiss,
  onUseDemo,
}: IntakeProps) {
  return (
    <div className="ins-chassis relative flex flex-1 flex-col gap-3">
      <Screws />
      <header className="px-2 pt-1">
        <h1 className="text-[15px] font-bold uppercase tracking-[0.3em] text-ink">
          Requirement <span className="text-accent">intake</span>
        </h1>
        <p className="ins-mono mt-1 max-w-[62ch] text-[11px] leading-relaxed text-ink-dim">
          Describe the system in your own words. Whatever you leave out becomes a
          question — never a guess. Nothing is generated until every blocking
          question has an answer that came from you.
        </p>
      </header>

      <Bay legend="requirement" className="flex-1">
        <div className="flex h-full flex-col p-3">
          <label htmlFor="req" className="sr-only">
            Requirement text
          </label>
          <textarea
            id="req"
            value={requirement}
            onChange={(e) => onRequirementChange(e.target.value)}
            spellCheck={false}
            placeholder="e.g. On a <board> with a <mcu>, read the <sensor> over I2C at <address>, and …"
            className="ins-face ins-mono min-h-[168px] flex-1 resize-none p-3 text-[12.5px] leading-relaxed text-ink outline-none placeholder:text-ink-faint"
          />

          <div className="mt-3">
            <span className="ins-mono text-[10px] uppercase tracking-[0.18em] text-ink-faint">
              examples — click to put one in the box, then edit it
            </span>
            <div className="mt-1.5 flex flex-col gap-1.5">
              {EXAMPLES.map((ex, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => onRequirementChange(ex)}
                  className="ins-key border border-line px-2.5 py-1.5 text-left text-[10.5px] leading-snug text-ink-dim transition-colors hover:border-accent-dim hover:text-ink"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        </div>
      </Bay>

      {error && <ErrorPlate text={error} onUseDemo={onUseDemo ?? undefined} />}

      <div className="flex items-center gap-3 px-2 pb-1">
        <button
          type="button"
          onClick={onAnalyze}
          disabled={busy || !requirement.trim()}
          className="ins-key border border-accent-dim px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.22em] text-accent transition-colors hover:bg-accent/10 disabled:cursor-not-allowed disabled:border-line disabled:text-ink-faint"
        >
          {busy ? "analysing…" : "analyse requirement ▸"}
        </button>
        {busy && (
          <span className="flex items-center gap-2">
            <Led tone="green" breathe />
            <span className="ins-mono text-[10px] uppercase tracking-[0.16em] text-ink-dim">
              extracting spec · asking the model for evidence spans
            </span>
          </span>
        )}
        {onDismiss && !busy && (
          <button
            type="button"
            onClick={onDismiss}
            className="ins-mono ml-auto text-[10px] uppercase tracking-[0.18em] text-ink-faint hover:text-ink-dim"
          >
            ✕ back to the board
          </button>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- step two */

function QuestionStep({
  questions,
  answers,
  busy,
  error,
  onAnswer,
  onDismiss,
  onUseDemo,
  requirement,
}: IntakeProps) {
  /* Ordered so the run's blockers come first: those are the ones that decide
     whether anything can be generated at all. */
  const ordered = useMemo(
    () =>
      [...questions].sort(
        (a, b) => Number(b.blocking) - Number(a.blocking),
      ),
    [questions],
  );

  const [index, setIndex] = useState(0);
  const [draft, setDraft] = useState<Record<string, string>>({});

  const q = ordered[index];
  const blockingTotal = ordered.filter((x) => x.blocking).length;
  const answeredBlocking = ordered.filter(
    (x) => x.blocking && (draft[x.id] ?? "").trim(),
  ).length;
  const ready = answeredBlocking === blockingTotal;
  const value = q ? (draft[q.id] ?? "") : "";

  const set = (v: string) =>
    q && setDraft((d) => ({ ...d, [q.id]: v }));

  const advance = () => setIndex((i) => Math.min(i + 1, ordered.length - 1));
  const isLast = index === ordered.length - 1;

  const submit = () => {
    const clean: Record<string, string> = {};
    for (const [k, v] of Object.entries(draft)) if (v.trim()) clean[k] = v.trim();
    onAnswer(clean);
  };

  if (!q) return null;

  return (
    <div className="ins-chassis relative flex flex-1 flex-col gap-3">
      <Screws />

      <header className="flex items-start justify-between gap-4 px-2 pt-1">
        <div>
          <h1 className="text-[15px] font-bold uppercase tracking-[0.3em] text-ink">
            Clarify <span className="text-accent">first</span>
          </h1>
          <p className="ins-mono mt-1 max-w-[62ch] text-[11px] leading-relaxed text-ink-dim">
            The pipeline could not ground these fields in anything you said. It
            will not fill them in for you and neither will this screen.
          </p>
        </div>
        <div className="text-right">
          <div className="ins-mono text-[10px] uppercase tracking-[0.18em] text-ink-faint">
            question {index + 1} of {ordered.length}
          </div>
          <div className="ins-mono mt-0.5 text-[10px] text-ink-faint">
            {answeredBlocking}/{blockingTotal} blocking answered
          </div>
        </div>
      </header>

      {/* progress ticks — one per question, filled as they are answered */}
      <div className="flex gap-1 px-2" aria-hidden>
        {ordered.map((x, i) => {
          const done = (draft[x.id] ?? "").trim().length > 0;
          return (
            <button
              key={x.id}
              type="button"
              onClick={() => setIndex(i)}
              title={x.field}
              className={`h-[3px] flex-1 transition-colors ${
                done
                  ? "bg-accent"
                  : i === index
                    ? "bg-ink-dim"
                    : x.blocking
                      ? "bg-red/40"
                      : "bg-line-2"
              }`}
            />
          );
        })}
      </div>

      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={q.id}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={SNAP}
          className="flex-1"
        >
          <Bay
            tone={q.blocking ? "alarm" : "dim"}
            legend={
              <span className="flex items-center gap-2">
                <Led tone={q.blocking ? "red" : "amber"} />
                {q.blocking ? "blocking" : "optional — adds detail"}
              </span>
            }
            right={
              <span className="ins-mono text-[10px] text-ink-faint">{q.field}</span>
            }
            className="h-full"
          >
            <div className="flex h-full flex-col gap-4 p-4">
              <p className="max-w-[64ch] text-[15px] leading-relaxed text-ink">
                {q.text}
              </p>

              {q.options.length > 0 ? (
                <div
                  role="radiogroup"
                  aria-label={q.text}
                  className="flex flex-wrap gap-2"
                >
                  {q.options.map((o) => {
                    const on = value === o;
                    return (
                      <button
                        key={o}
                        type="button"
                        role="radio"
                        aria-checked={on}
                        onClick={() => set(o)}
                        className={`ins-key flex items-center gap-2 border px-3 py-2 text-[11px] uppercase tracking-[0.14em] transition-colors ${
                          on
                            ? "border-accent-dim text-accent"
                            : "border-line text-ink-dim hover:text-ink"
                        }`}
                      >
                        <Led tone={on ? "green" : "off"} />
                        {o}
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div>
                  <label htmlFor={`a-${q.id}`} className="sr-only">
                    {q.text}
                  </label>
                  <input
                    id={`a-${q.id}`}
                    value={value}
                    autoComplete="off"
                    spellCheck={false}
                    onChange={(e) => set(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && value.trim() && !isLast) advance();
                    }}
                    placeholder="your answer — in your words"
                    className="ins-face ins-mono w-full max-w-[56ch] px-3 py-2.5 text-[13px] text-ink outline-none placeholder:text-ink-faint"
                  />
                </div>
              )}

              <p className="ins-mono max-w-[64ch] text-[10px] leading-relaxed text-ink-faint">
                {q.blocking
                  ? "This one gates the build. Nothing is generated while it is unanswered — the pipeline refuses rather than picking something plausible."
                  : "Optional. Leave it blank and the run proceeds; the field simply stays unstated rather than being assumed."}
              </p>

              <div className="mt-auto flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setIndex((i) => Math.max(0, i - 1))}
                  disabled={index === 0}
                  className="ins-key border border-line px-3 py-1.5 text-[10px] uppercase tracking-[0.18em] text-ink-dim disabled:opacity-35"
                >
                  ◂ back
                </button>
                {!isLast && (
                  <button
                    type="button"
                    onClick={advance}
                    className="ins-key border border-line px-3 py-1.5 text-[10px] uppercase tracking-[0.18em] text-ink-dim hover:text-ink"
                  >
                    {value.trim() ? "next ▸" : q.blocking ? "later ▸" : "skip ▸"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={submit}
                  disabled={!ready || busy}
                  title={
                    ready
                      ? undefined
                      : `${blockingTotal - answeredBlocking} blocking question(s) still unanswered`
                  }
                  className="ins-key ml-auto border border-accent-dim px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-accent transition-colors hover:bg-accent/10 disabled:cursor-not-allowed disabled:border-line disabled:text-ink-faint"
                >
                  {busy
                    ? "re-analysing…"
                    : ready
                      ? "re-analyse with these answers ▸"
                      : `${blockingTotal - answeredBlocking} blocking left`}
                </button>
              </div>
            </div>
          </Bay>
        </motion.div>
      </AnimatePresence>

      {error && <ErrorPlate text={error} onUseDemo={onUseDemo ?? undefined} />}

      {/* the ledger: what the spec already stands on */}
      <Bay
        legend="answers on file"
        right={
          <span className="ins-mono text-[10px] text-ink-faint">
            {Object.keys(answers).length} accepted
          </span>
        }
      >
        <div className="max-h-[104px] overflow-auto p-2.5">
          <p className="ins-mono mb-1.5 text-[10px] text-ink-faint">
            requirement · {requirement.length} chars stated by you
          </p>
          <Rule />
          {Object.keys(answers).length === 0 ? (
            <p className="ins-mono pt-1.5 text-[10px] text-ink-faint">
              none yet — every spec value so far traces to your requirement text
            </p>
          ) : (
            <ul className="flex flex-col gap-0.5 pt-1.5">
              {Object.entries(answers).map(([k, v]) => (
                <li key={k} className="flex gap-2">
                  <span className="ins-mono shrink-0 text-[10px] text-ink-faint">
                    {k}
                  </span>
                  <span className="ins-mono truncate text-[10px] text-accent-dim">
                    {v}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Bay>

      {onDismiss && (
        <div className="px-2 pb-1">
          <button
            type="button"
            onClick={onDismiss}
            className="ins-mono text-[10px] uppercase tracking-[0.18em] text-ink-faint hover:text-ink-dim"
          >
            ✕ back to the board — the run stays blocked until these are answered
          </button>
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------- shared */

export function ErrorPlate({
  text,
  onUseDemo,
}: {
  text: string;
  onUseDemo?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 border border-red/50 bg-red/5 px-3 py-2.5"
    >
      <span className="mt-[3px]">
        <Led tone="red" blink />
      </span>
      <div className="min-w-0 flex-1">
        <p className="ins-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-red">
          backend error — nothing below is a result
        </p>
        <p className="ins-mono mt-0.5 max-w-[72ch] text-[11px] leading-relaxed text-ink-dim">
          {text}
        </p>
        {onUseDemo && (
          <p className="ins-mono mt-1.5 text-[10px] leading-relaxed text-ink-faint">
            Nothing is being shown in place of the failed call.{" "}
            <button
              type="button"
              onClick={onUseDemo}
              className="text-amber underline decoration-amber/50 underline-offset-2 hover:text-amber/80"
            >
              Switch to the demo fixture
            </button>{" "}
            if you want to see the screen work — it will be labelled as recorded
            data for as long as it is on.
          </p>
        )}
      </div>
    </div>
  );
}
