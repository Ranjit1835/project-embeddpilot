"use client";

/* Panel furniture for the Resource Map: rack chassis, screws, indicator lamps,
   engraved sub-headers. Deliberately dumb — no state, no data. */

import { motion } from "framer-motion";
import { useId, type ReactNode } from "react";

export const SNAP = { duration: 0.22, ease: [0.22, 1, 0.36, 1] as const };
export const GLIDE = { duration: 0.55, ease: [0.65, 0, 0.35, 1] as const };

export const LED_COLOR = {
  green: "#3fe081",
  amber: "#e0a63c",
  red: "#e5533c",
  cyan: "#2e88ad",
  off: "#1b242d",
} as const;

export type LedTone = keyof typeof LED_COLOR;

export function Led({
  tone = "off",
  blink,
  breathe,
  label,
}: {
  tone?: LedTone;
  blink?: boolean;
  breathe?: boolean;
  label?: string;
}) {
  const cls = [
    "ins-led",
    tone === "off" && "ins-led-off",
    blink && "ins-blink",
    breathe && "ins-breathe",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <span
      className={cls}
      style={tone === "off" ? undefined : { ["--led" as string]: LED_COLOR[tone] }}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  );
}

/** Four corner fasteners on the rack ear. */
export function Screws() {
  return (
    <>
      <span className="ins-screw" style={{ top: 6, left: 6 }} aria-hidden />
      <span className="ins-screw" style={{ top: 6, right: 6 }} aria-hidden />
      <span className="ins-screw" style={{ bottom: 6, left: 6 }} aria-hidden />
      <span className="ins-screw" style={{ bottom: 6, right: 6 }} aria-hidden />
    </>
  );
}

/** Engraved section legend — the small stamped caption above every module. */
export function Legend({
  children,
  tone = "dim",
  className = "",
}: {
  children: ReactNode;
  tone?: "dim" | "accent" | "alarm";
  className?: string;
}) {
  const color = {
    dim: "text-ink-dim",
    accent: "text-accent",
    alarm: "text-red",
  }[tone];
  return (
    <span
      className={`ins-etch text-[10px] font-semibold uppercase tracking-[0.28em] ${color} ${className}`}
    >
      {children}
    </span>
  );
}

/** A module bay inside the face plate. */
export function Bay({
  legend,
  right,
  tone = "dim",
  children,
  className = "",
  glass,
}: {
  legend: ReactNode;
  right?: ReactNode;
  tone?: "dim" | "accent" | "alarm";
  children: ReactNode;
  className?: string;
  glass?: boolean;
}) {
  return (
    <section
      className={`ins-panel flex min-h-0 min-w-0 flex-col ${glass ? "ins-glass" : ""} ${className}`}
    >
      {/* wraps rather than overflows: a bay legend plus its right-hand readout
          is wider than 360px more often than not */}
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-line px-3 py-[7px]">
        <Legend tone={tone}>{legend}</Legend>
        {right}
      </header>
      <div className="min-h-0 min-w-0 flex-1">{children}</div>
    </section>
  );
}

/** Rotary-feel two-position selector. Two real buttons, one physical body. */
export function ModeSwitch<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: T;
  options: { value: T; label: string; tone: LedTone }[];
  onChange: (v: T) => void;
  ariaLabel: string;
}) {
  /* The knob is a shared-layout element, so its id must be unique PER SWITCH.
     A literal "ins-mode-knob" made the source switch and the demo-state switch
     one animation target: throwing either one flew the knob across the header
     into the other. */
  const knob = useId();
  return (
    <div className="ins-switch shrink-0" role="group" aria-label={ariaLabel}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(o.value)}
            className={`relative flex items-center gap-1.5 rounded-[2px] px-2.5 py-[9px] text-[10px] font-semibold uppercase tracking-[0.16em] transition-colors sm:gap-2 sm:px-3 sm:py-[5px] sm:tracking-[0.2em] ${
              on ? "text-ink" : "text-ink-faint hover:text-ink-dim"
            }`}
          >
            {on && (
              <motion.span
                layoutId={knob}
                transition={SNAP}
                className="ins-key absolute inset-0 rounded-[2px]"
                aria-hidden
              />
            )}
            <span className="relative z-10 flex items-center gap-2">
              <Led tone={on ? o.tone : "off"} />
              {o.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** Numbered stage strip. The active stage carries a sliding phosphor bar.

    Five stages do not fit across 360px, and the honest options are to drop
    stages or to let the strip pan. It pans: every stage stays present and
    legible, the strip scrolls inside its own track, and the page does not.
    Above lg `.ins-scroll-x` reverts to `overflow: visible`, so the desktop
    ribbon — including the bar that hangs 7px below it — is unchanged. */
export function StepRibbon({ steps, active }: { steps: string[]; active: number }) {
  return (
    <nav
      aria-label="Workspace stages"
      className="ins-scroll-x ins-fade-x flex max-w-full items-stretch lg:justify-end"
    >
      {steps.map((s, i) => {
        const on = i === active;
        return (
          <span
            key={s}
            aria-current={on ? "step" : undefined}
            className={`relative flex shrink-0 items-center gap-1.5 whitespace-nowrap px-2.5 py-1 pb-2 text-[10px] font-medium uppercase tracking-[0.14em] lg:px-3 lg:pb-1 lg:tracking-[0.18em] ${
              on ? "text-accent" : "text-ink-faint"
            }`}
          >
            <span className="ins-mono text-[10px] opacity-70">{i + 1}</span>
            {s}
            {on && (
              <motion.span
                layoutId="ins-step-bar"
                transition={SNAP}
                className="absolute inset-x-1.5 bottom-[3px] h-[2px] bg-accent lg:-bottom-[7px]"
                style={{ boxShadow: "0 0 8px #3fe081" }}
                aria-hidden
              />
            )}
          </span>
        );
      })}
    </nav>
  );
}

/** Hairline with a centred tick, used to break dense stacks. */
export function Rule() {
  return <div className="h-px w-full bg-line" aria-hidden />;
}
