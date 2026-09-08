"use client";

/* The conversation. One running thread the user can scroll back through:
   their requirement, our questions, their answers, and what the run did.
   Context is the thread — it does not reset between rounds, because the
   engineers' complaint was that answering felt like starting over. */

import { motion } from "framer-motion";
import { useEffect, useRef } from "react";
import type { V2Question } from "../../lib/v2-types";

export type Turn =
  | { kind: "you"; text: string }
  | { kind: "system"; text: string; tone?: "normal" | "warn" | "bad" | "good" }
  | { kind: "questions"; questions: V2Question[]; answered: Record<string, string> };

export function Conversation({
  turns,
  pending,
}: {
  turns: Turn[];
  pending: string | null;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, pending]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
      {turns.length === 0 && (
        <div className="m-auto max-w-[46ch] text-center">
          <p className="text-[13px] leading-relaxed text-ink-dim">
            Describe the system you want, in your own words.
          </p>
          <p className="mt-2 font-mono text-[11px] leading-relaxed text-ink-faint">
            Anything you leave out becomes a question — never a guess. Nothing is
            generated until every blocking question has an answer that came from
            you.
          </p>
        </div>
      )}

      {turns.map((t, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.18 }}
          className={t.kind === "you" ? "flex justify-end" : ""}
        >
          {t.kind === "you" && (
            <div className="max-w-[86%] rounded-lg rounded-br-sm border border-accent-dim/40 bg-accent/5 px-3 py-2">
              <p className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-ink">
                {t.text}
              </p>
            </div>
          )}

          {t.kind === "system" && (
            <div
              className={`max-w-[92%] rounded-lg rounded-bl-sm border px-3 py-2 ${
                t.tone === "bad"
                  ? "border-red/50 bg-red/5"
                  : t.tone === "warn"
                    ? "border-amber/50 bg-amber/5"
                    : t.tone === "good"
                      ? "border-accent-dim/50 bg-accent/5"
                      : "border-line bg-panel"
              }`}
            >
              <p
                className={`whitespace-pre-wrap font-mono text-[11.5px] leading-relaxed ${
                  t.tone === "bad"
                    ? "text-red"
                    : t.tone === "warn"
                      ? "text-amber"
                      : t.tone === "good"
                        ? "text-accent"
                        : "text-ink-dim"
                }`}
              >
                {t.text}
              </p>
            </div>
          )}

          {t.kind === "questions" && (
            <div className="max-w-[92%] rounded-lg rounded-bl-sm border border-line bg-panel px-3 py-2">
              <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint">
                {t.questions.length} thing{t.questions.length === 1 ? "" : "s"} I
                could not ground in what you said
              </p>
              <ul className="mt-1.5 flex flex-col gap-1">
                {t.questions.map((q) => (
                  <li key={q.id} className="flex items-start gap-2">
                    <span
                      className={`mt-[6px] h-1.5 w-1.5 shrink-0 rounded-full ${
                        q.blocking ? "bg-red" : "bg-ink-faint"
                      }`}
                    />
                    <span className="min-w-0">
                      <span className="text-[12px] leading-relaxed text-ink">
                        {q.text}
                      </span>
                      {t.answered[q.id] && (
                        <span className="ml-1.5 font-mono text-[11px] text-accent">
                          → {t.answered[q.id]}
                        </span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </motion.div>
      ))}

      {pending && (
        <div className="flex items-center gap-2 text-ink-faint">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
          <span className="font-mono text-[11px]">{pending}</span>
        </div>
      )}
      <div ref={end} />
    </div>
  );
}
