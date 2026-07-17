"use client";

/* Shared primitives — instrument-grade: compact, bordered, no decoration. */

import { motion } from "framer-motion";
import type { ReactNode } from "react";

export const EASE = { duration: 0.2, ease: "easeOut" as const };

export function Panel({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`border border-line bg-panel rounded-sm ${className}`}>
      {title && (
        <h2 className="px-3 py-1.5 border-b border-line text-[11px] uppercase tracking-[0.14em] text-ink-dim select-none">
          {title}
        </h2>
      )}
      {children}
    </section>
  );
}

export function Button({
  children,
  onClick,
  kind = "default",
  disabled,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  kind?: "default" | "primary" | "danger-ghost";
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  const styles = {
    default:
      "border-line-2 text-ink hover:border-ink-faint hover:bg-panel-2",
    primary:
      "border-accent-dim bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-40",
    "danger-ghost":
      "border-transparent text-ink-faint hover:text-red hover:border-red/40",
  }[kind];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`border rounded-sm px-3 py-1.5 text-[13px] font-medium transition-colors disabled:cursor-not-allowed ${styles}`}
    >
      {children}
    </button>
  );
}

export type Verdict =
  | "validated"
  | "validated-with-unverified-fields"
  | "unvalidated"
  | "failed"
  | "template-path";

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const spec: Record<Verdict, { label: string; cls: string }> = {
    validated: {
      label: "VALIDATED",
      cls: "text-accent border-accent-dim bg-accent/10",
    },
    "validated-with-unverified-fields": {
      label: "VALIDATED — UNVERIFIED FIELDS",
      cls: "text-amber border-amber/50 bg-amber/10",
    },
    unvalidated: {
      label: "FAILED — UNVALIDATED OUTPUT",
      cls: "text-red border-red/50 bg-red/10",
    },
    failed: {
      label: "FAILED",
      cls: "text-red border-red/50 bg-red/10",
    },
    "template-path": {
      label: "TEMPLATE PATH",
      cls: "text-accent border-accent-dim bg-accent/10",
    },
  };
  const { label, cls } = spec[verdict];
  return (
    <motion.span
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={EASE}
      className={`inline-block border rounded-sm px-2.5 py-1 font-mono text-[12px] tracking-wide ${cls}`}
    >
      {label}
    </motion.span>
  );
}

/** ✓ / ✗ / skipped — skipped is a visible neutral state, never hidden. */
export function CheckGlyph({ state }: { state: "pass" | "fail" | "skipped" | "pending" }) {
  const spec = {
    pass: { glyph: "✓", cls: "text-accent" },
    fail: { glyph: "✕", cls: "text-red" },
    skipped: { glyph: "–", cls: "text-ink-faint" },
    pending: { glyph: "·", cls: "text-ink-faint" },
  }[state];
  return (
    <motion.span
      key={state}
      initial={{ opacity: 0, scale: 0.6 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={EASE}
      className={`inline-block w-4 text-center font-mono ${spec.cls}`}
      aria-label={state}
    >
      {spec.glyph}
    </motion.span>
  );
}

export function Hex({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[13px]">{children}</span>;
}

export function Confidence({ level }: { level?: "high" | "medium" | "low" }) {
  if (!level) return <span className="text-ink-faint">—</span>;
  const cls = {
    high: "text-accent",
    medium: "text-amber",
    low: "text-red",
  }[level];
  return <span className={`font-mono text-[11px] uppercase ${cls}`}>{level}</span>;
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1 text-[12px] text-ink-dim">
      <span className="uppercase tracking-[0.1em] text-[10px]">{label}</span>
      {children}
    </label>
  );
}

export const inputCls =
  "bg-panel-2 border border-line-2 rounded-sm px-2.5 py-1.5 text-[13px] text-ink " +
  "placeholder:text-ink-faint focus:border-accent-dim focus:outline-none w-full";
