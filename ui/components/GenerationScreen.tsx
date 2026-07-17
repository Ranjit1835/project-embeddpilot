"use client";

/* Screen 3: live pipeline — router decision, attempt timeline, validation
   checklist. Retries are a feature: failed attempts stay visible with their
   diagnostics. Skipped checks render as a distinct neutral state. */

import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import type { JobEvent, RouteDecision, ValidationReport } from "../lib/types";
import { CheckGlyph, EASE, Panel, VerdictBadge } from "./ui";

export interface Attempt {
  n: number;
  report?: ValidationReport;
}

export function attemptsFromEvents(events: JobEvent[]): {
  decision: RouteDecision | null;
  attempts: Attempt[];
} {
  let decision: RouteDecision | null = null;
  const attempts: Attempt[] = [];
  for (const e of events) {
    if (e.type === "route") decision = e.decision;
    else if (e.type === "attempt_start") attempts.push({ n: e.attempt });
    else if (e.type === "attempt_report") {
      const a = attempts.find((x) => x.n === e.attempt);
      if (a) a.report = e.report;
    }
  }
  return { decision, attempts };
}

const CHECKS: [string, string][] = [
  ["compile", "Compile (zero warnings)"],
  ["register_crosscheck", "Register / opcode cross-check"],
  ["static_analysis", "Static analysis"],
];

export function GenerationScreen({
  decision,
  attempts,
  running,
  error,
}: {
  decision: RouteDecision | null;
  attempts: Attempt[];
  running: boolean;
  error: string | null;
}) {
  return (
    <div className="grid gap-4 w-full max-w-3xl mx-auto">
      <Panel title="Route">
        <div className="p-3 grid gap-1.5">
          {decision ? (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={EASE}>
              <span className="font-mono text-[13px] text-accent">
                {decision.user_label}
              </span>
              <p className="text-[12px] text-ink-dim mt-1">{decision.reason}</p>
            </motion.div>
          ) : (
            <span className="text-[13px] text-ink-faint font-mono">routing…</span>
          )}
        </div>
      </Panel>

      <AnimatePresence>
        {attempts.map((a) => (
          <motion.div
            key={a.n}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={EASE}
          >
            <AttemptPanel attempt={a} isLive={running && !a.report} />
          </motion.div>
        ))}
      </AnimatePresence>

      {error && (
        <Panel title="Error">
          <p role="alert" className="p-3 text-[13px] text-red font-mono">
            {error}
          </p>
        </Panel>
      )}
    </div>
  );
}

function AttemptPanel({ attempt, isLive }: { attempt: Attempt; isLive: boolean }) {
  const [showDiag, setShowDiag] = useState(false);
  const report = attempt.report;
  const failures = report?.failures ?? [];

  return (
    <Panel title={`Attempt ${attempt.n}`}>
      <div className="p-3 grid gap-2">
        <ul className="grid gap-1">
          {CHECKS.map(([key, label]) => {
            const state = report ? (report.checks[key] ?? "skipped") : "pending";
            return (
              <li key={key} className="flex items-center gap-2.5 h-6 font-mono text-[13px]">
                {isLive ? (
                  <motion.span
                    className="inline-block w-4 text-center text-ink-faint"
                    animate={{ opacity: [0.3, 1, 0.3] }}
                    transition={{ repeat: Infinity, duration: 1.2 }}
                  >
                    ·
                  </motion.span>
                ) : (
                  <CheckGlyph state={state} />
                )}
                <span className={state === "skipped" ? "text-ink-faint" : "text-ink"}>
                  {label}
                  {key === "compile" && report?.notes?.length
                    ? formatCompilerNote(report.notes)
                    : ""}
                  {state === "skipped" && " — skipped"}
                </span>
              </li>
            );
          })}
        </ul>

        {report && (
          <div className="flex items-center gap-3">
            <VerdictBadge
              verdict={report.status === "failed" ? "failed" : report.status}
            />
            {failures.length > 0 && (
              <button
                onClick={() => setShowDiag((s) => !s)}
                aria-expanded={showDiag}
                className="text-[12px] text-ink-dim hover:text-ink underline underline-offset-2"
              >
                {showDiag ? "hide" : "show"} diagnostics ({failures.length})
              </button>
            )}
          </div>
        )}

        <AnimatePresence>
          {showDiag && failures.length > 0 && (
            <motion.pre
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={EASE}
              className="overflow-x-auto bg-bg border border-line rounded-sm p-2.5 font-mono text-[12px] text-red/90 leading-relaxed"
            >
              {failures
                .map(
                  (f) =>
                    `[${f.check}] ${f.file}${f.line ? ":" + f.line : ""}\n${f.message}`,
                )
                .join("\n\n")}
            </motion.pre>
          )}
        </AnimatePresence>
      </div>
    </Panel>
  );
}

function formatCompilerNote(notes: string[]): string {
  const cc = notes.find((n) => n.startsWith("compiler:"));
  return cc ? ` — ${cc.replace("compiler: ", "")}` : "";
}
