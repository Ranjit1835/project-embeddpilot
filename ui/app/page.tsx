"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useRef, useState, useSyncExternalStore } from "react";
import { isDemoActive, subscribeDemoFlag } from "../lib/demo";
import {
  GenerationScreen,
  attemptsFromEvents,
  type Attempt,
} from "../components/GenerationScreen";
import { InputScreen } from "../components/InputScreen";
import { ResultsScreen } from "../components/ResultsScreen";
import { ReviewScreen } from "../components/ReviewScreen";
import { EASE } from "../components/ui";
import { jobSnapshot, startGenerate, subscribeJob } from "../lib/api";
import type {
  GenerationResult,
  JobEvent,
  RegisterMap,
  RouteDecision,
} from "../lib/types";

type Step = "input" | "review" | "generate" | "results";

const STEPS: [Step, string][] = [
  ["input", "Datasheet"],
  ["review", "Review map"],
  ["generate", "Generate + validate"],
  ["results", "Result"],
];

export default function Home() {
  const [step, setStep] = useState<Step>("input");
  const [map, setMap] = useState<RegisterMap | null>(null);
  // no silent platform default — it is an explicit choice on the review screen
  const [platform, setPlatform] = useState("");
  const [decision, setDecision] = useState<RouteDecision | null>(null);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [genRunning, setGenRunning] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerationResult | null>(null);
  const [jobId, setJobId] = useState("");
  const events = useRef<JobEvent[]>([]);
  const unsub = useRef<(() => void) | null>(null);
  const demo = useSyncExternalStore(subscribeDemoFlag, isDemoActive, () => false);

  const onMapReady = useCallback((m: RegisterMap, p: string) => {
    setMap(m);
    setPlatform(p);
    setStep("review");
  }, []);

  const onGenerate = useCallback(
    async (m: RegisterMap, p: string, edits: string[]) => {
      setStep("generate");
      setGenRunning(true);
      setGenError(null);
      setDecision(null);
      setAttempts([]);
      events.current = [];
      try {
        const id = await startGenerate({
          register_map: m,
          platform: p,
          edits,
        });
        setJobId(id);
        unsub.current = subscribeJob(id, async (e) => {
          events.current.push(e);
          const parsed = attemptsFromEvents(events.current);
          setDecision(parsed.decision);
          setAttempts(parsed.attempts);
          if (e.type === "job_done") {
            setGenRunning(false);
            if (e.status === "error") {
              setGenError(e.error ?? "generation failed");
            } else {
              const snap = await jobSnapshot(id);
              setResult(snap.result as GenerationResult);
              setStep("results");
            }
          }
        });
      } catch (err) {
        setGenRunning(false);
        setGenError(String(err));
      }
    },
    [],
  );

  const startOver = useCallback(() => {
    unsub.current?.();
    setStep("input");
    setMap(null);
    setResult(null);
    setDecision(null);
    setAttempts([]);
    setGenError(null);
  }, []);

  return (
    <div className="flex flex-col min-h-screen">
      <header className="border-b border-line bg-panel/60 backdrop-blur px-5 py-2.5 flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-baseline gap-2 select-none">
          <span className="font-mono text-[15px] tracking-tight text-ink">
            embedd<span className="text-accent">pilot</span>
          </span>
          <span className="font-mono text-[10px] text-ink-faint">v1.6</span>
        </div>
        <nav aria-label="pipeline steps" className="flex gap-0.5">
          {STEPS.map(([key, label], i) => {
            const activeIdx = STEPS.findIndex(([k]) => k === step);
            const state = i < activeIdx ? "done" : i === activeIdx ? "active" : "todo";
            return (
              <div
                key={key}
                aria-current={state === "active" ? "step" : undefined}
                className={`px-3 py-1 font-mono text-[11px] border-b-2 transition-colors ${
                  state === "active"
                    ? "border-accent text-ink"
                    : state === "done"
                      ? "border-accent-dim text-ink-dim"
                      : "border-transparent text-ink-faint"
                }`}
              >
                {i + 1} {label}
              </div>
            );
          })}
        </nav>
      </header>

      {demo && (
        <div
          role="note"
          className="border-b border-amber/30 bg-amber/10 px-5 py-1.5 font-mono text-[11.5px] text-amber"
        >
          recorded case study — replaying real pipeline runs captured
          2026-07-17; clone the repo and run the FastAPI backend for live
          generation against your own datasheets
        </div>
      )}

      <main className="flex-1 px-5 py-6 w-full max-w-6xl mx-auto">
        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={EASE}
          >
            {step === "input" && <InputScreen onMapReady={onMapReady} />}
            {step === "review" && map && (
              <ReviewScreen map={map} platform={platform} onGenerate={onGenerate} />
            )}
            {step === "generate" && (
              <GenerationScreen
                decision={decision}
                attempts={attempts}
                running={genRunning}
                error={genError}
              />
            )}
            {step === "results" && result && (
              <ResultsScreen result={result} jobId={jobId} onStartOver={startOver} />
            )}
          </motion.div>
        </AnimatePresence>
      </main>

      <footer className="border-t border-line px-5 py-2 font-mono text-[10.5px] text-ink-faint flex justify-between">
        <span>generator is never the judge — validation runs mechanically separate</span>
        <span>ingest → review → generate → validate</span>
      </footer>
    </div>
  );
}
