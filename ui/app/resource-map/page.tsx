"use client";

/* The V2 workspace hero. The BOARD is the screen — not a file tree, not a chat
   rail. Left bay is the composed system rendered as copper; right bays are the
   instruments reading it. State A shows a real double-booking as an alarm;
   auto-fix clears it and the emulation bay proves the firmware actually runs.
   The verdict rail only reaches WORKING after emulation asserts — an unverified
   system never gets to claim it works. */

import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { BoardView } from "../../components/resource-map/BoardView";
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
  CONFLICT,
  devices,
  rail,
  TARGET,
  TEMP_TRACE,
  THRESHOLD_C,
  UART,
  verdict,
  type CheckState,
  type LineTone,
  type Mode,
} from "../../lib/resource-map-mock";

const STAGES = ["requirements", "devices", "resource map", "code", "run"];

const RAIL_TONE: Record<CheckState, LedTone> = {
  pass: "green",
  warn: "amber",
  fail: "red",
  pending: "off",
};

const RAIL_MARK: Record<CheckState, string> = {
  pass: "✓",
  warn: "⚠",
  fail: "✕",
  pending: "○",
};

const LINE_CLASS: Record<LineTone, string> = {
  dim: "text-ink-faint",
  ink: "text-ink",
  good: "text-accent",
  warn: "text-amber",
  bad: "text-red",
};

export default function ResourceMapPage() {
  const [mode, setMode] = useState<Mode>("conflict");
  const conflict = mode === "conflict";
  const v = verdict(mode);

  return (
    <div className="ins-room flex min-h-screen flex-col">
      {/* ------------------------------------------------ chassis header */}
      <header className="ins-chassis relative flex items-center justify-between gap-6 border-b border-line px-5 py-2.5">
        <Screws />
        <div className="flex items-baseline gap-3">
          <span className="text-[13px] font-bold uppercase tracking-[0.3em] text-ink">
            Embedd<span className="text-accent">Pilot</span>
          </span>
          <span className="ins-mono text-[10px] uppercase tracking-[0.18em] text-ink-faint">
            project · greenhouse
          </span>
        </div>

        <StepRibbon steps={STAGES} active={2} />

        <ModeSwitch<Mode>
          ariaLabel="Board state"
          value={mode}
          onChange={setMode}
          options={[
            { value: "conflict", label: "as designed", tone: "red" },
            { value: "resolved", label: "after fix", tone: "green" },
          ]}
        />
      </header>

      {/* ------------------------------------------------------ the bench */}
      <main className="grid min-h-0 flex-1 gap-3 p-3 lg:grid-cols-[minmax(0,1.55fr)_minmax(340px,0.95fr)]">
        {/* the board is the hero */}
        <Bay
          glass
          tone={conflict ? "alarm" : "accent"}
          legend={`target · ${TARGET.mcu}`}
          right={
            <span className="ins-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint">
              {TARGET.board}
            </span>
          }
          className="min-h-[420px]"
        >
          <BoardView mode={mode} />
        </Bay>

        {/* instrument stack */}
        <div className="flex min-h-0 flex-col gap-3">
          <Bay legend="devices" right={<Count n={devices(mode).length} />}>
            <ul className="divide-y divide-line">
              {devices(mode).map((d) => (
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
                      {d.checks.map((c) => (
                        <span
                          key={c.label}
                          className={`ins-mono text-[10px] ${
                            c.ok ? "text-accent-dim" : "text-red"
                          }`}
                        >
                          {c.ok ? "✓" : "✕"} {c.label}
                        </span>
                      ))}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </Bay>

          {/* the swap: alarm bay -> emulation bay */}
          <AnimatePresence mode="wait" initial={false}>
            {conflict ? (
              <motion.div
                key="conflict"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={SNAP}
                className="min-h-0 flex-1"
              >
                <ConflictBay onFix={() => setMode("resolved")} />
              </motion.div>
            ) : (
              <motion.div
                key="run"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={SNAP}
                className="min-h-0 flex-1"
              >
                <EmulationBay />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>

      {/* -------------------------------------------------- verdict rail */}
      <footer className="ins-chassis border-t border-line px-3 py-2">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          {rail(mode).map((c) => (
            <div key={c.id} className="flex items-center gap-2">
              <Led tone={RAIL_TONE[c.state]} />
              <span
                className={`ins-mono text-[11px] ${
                  c.state === "pass"
                    ? "text-accent"
                    : c.state === "warn"
                      ? "text-amber"
                      : c.state === "fail"
                        ? "text-red"
                        : "text-ink-faint"
                }`}
              >
                {RAIL_MARK[c.state]} {c.label}
              </span>
              <span className="ins-mono text-[10px] text-ink-faint">{c.note}</span>
            </div>
          ))}

          <motion.div
            layout
            transition={GLIDE}
            className={`ml-auto flex items-center gap-2 border px-3 py-1 ${
              v.tone === "good"
                ? "border-accent-dim text-accent ins-glow"
                : "border-red/50 text-red ins-blink"
            }`}
          >
            <span className="ins-mono text-[11px] font-bold tracking-[0.18em]">
              {v.label}
            </span>
          </motion.div>
        </div>
        {v.tone === "good" && (
          <p className="mt-1.5 ins-mono text-[10px] text-ink-faint">
            emulated only — behaviour asserted in Renode against mocked devices;
            physical bring-up is still a human step.
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

function ConflictBay({ onFix }: { onFix: () => void }) {
  return (
    <Bay
      tone="alarm"
      legend={
        <span className="flex items-center gap-2">
          <span className="ins-blink">⚠</span> conflicts
        </span>
      }
      right={<Count n={1} />}
      className="h-full"
    >
      <div className="flex h-full flex-col">
        {/* hazard tape — a strip, so the panel body stays readable */}
        <div className="ins-hazard h-[6px] shrink-0" aria-hidden />

        <div className="flex min-h-0 flex-1 flex-col gap-2 p-3">
          <div>
            <p className="text-[13px] font-bold tracking-wide text-red">
              {CONFLICT.headline}
            </p>
            <p className="ins-mono mt-0.5 text-[10px] text-ink-faint">
              {CONFLICT.rule}
            </p>
          </div>

        <Rule />

        <ul className="flex flex-col gap-1.5">
          {CONFLICT.claimants.map((c) => (
            <li key={c.net} className="flex items-center gap-2">
              <span
                className={`h-2 w-2 shrink-0 ${
                  c.kind === "bus" ? "bg-accent" : "bg-red"
                }`}
                aria-hidden
              />
              <span className="ins-mono text-[11px] text-ink">{c.net}</span>
              <span className="ins-mono text-[10px] text-ink-faint">
                {c.owners}
              </span>
            </li>
          ))}
        </ul>

          <div className="mt-auto flex items-center justify-between gap-3 pt-2">
            <span className="ins-mono text-[10px] uppercase tracking-[0.14em] text-ink-dim">
              {CONFLICT.remedy} → {CONFLICT.suggestion}
            </span>
            <button
              type="button"
              onClick={onFix}
              className="ins-key border border-accent-dim px-3 py-[6px] text-[10px] font-semibold uppercase tracking-[0.2em] text-accent transition-colors hover:bg-accent/10"
            >
              auto-fix ▸ {CONFLICT.suggestion}
            </button>
          </div>
        </div>
      </div>
    </Bay>
  );
}

function EmulationBay() {
  return (
    <Bay
      glass
      tone="accent"
      legend="emulation · renode"
      right={
        <span className="flex items-center gap-1.5">
          <Led tone="green" />
          <span className="ins-mono text-[10px] uppercase tracking-[0.16em] text-accent">
            6/6 pass
          </span>
        </span>
      }
      className="h-full"
    >
      <div className="flex h-full min-h-0 flex-col">
        <Scope />
        <Rule />
        <div className="ins-face min-h-0 flex-1 overflow-auto p-2.5">
          {UART.map((l, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: i * 0.035, duration: 0.2 }}
              className="flex gap-2 whitespace-pre"
            >
              {l.t && (
                <span className="ins-mono text-[10px] text-ink-faint">{l.t}</span>
              )}
              <span className={`ins-mono text-[10.5px] ${LINE_CLASS[l.tone]}`}>
                {l.text}
              </span>
            </motion.div>
          ))}
          <span className="ins-caret ins-mono text-[10.5px] text-accent">▌</span>
        </div>
      </div>
    </Bay>
  );
}

/** Temperature trace with the threshold that trips the relay. */
function Scope() {
  const W = 320;
  const H = 64;
  const lo = 22;
  const hi = 33;
  const x = (i: number) => (i / (TEMP_TRACE.length - 1)) * W;
  const y = (t: number) => H - ((t - lo) / (hi - lo)) * H;
  const d = TEMP_TRACE.map((t, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(t).toFixed(1)}`).join(" ");
  const trip = TEMP_TRACE.findIndex((t) => t > THRESHOLD_C);

  return (
    <div className="relative px-2.5 pt-2">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-[64px] w-full"
        role="img"
        aria-label={`Temperature trace crossing the ${THRESHOLD_C} degree threshold`}
      >
        <line
          x1={0}
          x2={W}
          y1={y(THRESHOLD_C)}
          y2={y(THRESHOLD_C)}
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
        {trip > -1 && (
          <circle cx={x(trip)} cy={y(TEMP_TRACE[trip])} r={3} fill="#e0a63c" />
        )}
      </svg>
      <span className="ins-mono absolute right-3 top-2 text-[9px] text-amber">
        {THRESHOLD_C.toFixed(1)} °C
      </span>
    </div>
  );
}
