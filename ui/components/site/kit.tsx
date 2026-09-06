/* Server-safe primitives for the platform pages.
   Same instrument vocabulary as the workspace: etched legends, bordered bays,
   phosphor accents. No state, no client JS. */

import Link from "next/link";
import type { ReactNode } from "react";

/* ------------------------------------------------------------------ layout */

export function Container({
  children,
  className = "",
  wide,
}: {
  children: ReactNode;
  className?: string;
  wide?: boolean;
}) {
  return (
    <div
      className={`mx-auto w-full px-5 sm:px-7 lg:px-10 ${
        wide ? "max-w-[1360px]" : "max-w-[1180px]"
      } ${className}`}
    >
      {children}
    </div>
  );
}

export function Rule({ className = "" }: { className?: string }) {
  return <div className={`site-rule w-full ${className}`} aria-hidden />;
}

/* ----------------------------------------------------------------- legends */

/** The stamped caption above every module. Uppercase, tracked, engraved. */
export function Legend({
  children,
  tone = "dim",
  className = "",
}: {
  children: ReactNode;
  tone?: "dim" | "accent" | "amber" | "red";
  className?: string;
}) {
  const color = {
    dim: "text-ink-faint",
    accent: "text-accent",
    amber: "text-amber",
    red: "text-red",
  }[tone];
  return (
    <span
      className={`site-legend site-etch text-[10px] font-semibold uppercase leading-none tracking-[0.26em] ${color} ${className}`}
    >
      {children}
    </span>
  );
}

export function Led({
  tone = "off",
  blink,
  breathe,
}: {
  tone?: "green" | "amber" | "red" | "cyan" | "off";
  blink?: boolean;
  breathe?: boolean;
}) {
  const color = {
    green: "#3fe081",
    amber: "#e0a63c",
    red: "#e5533c",
    cyan: "#2e88ad",
    off: "",
  }[tone];
  return (
    <span
      aria-hidden
      className={[
        "site-led",
        tone === "off" && "site-led-off",
        blink && "site-blink",
        breathe && "site-breathe",
      ]
        .filter(Boolean)
        .join(" ")}
      style={tone === "off" ? undefined : { ["--led" as string]: color }}
    />
  );
}

/* ------------------------------------------------------------------ panels */

/** A module bay: engraved header strip over a recessed body. */
export function Bay({
  legend,
  right,
  tone = "dim",
  children,
  className = "",
  glass,
}: {
  legend?: ReactNode;
  right?: ReactNode;
  tone?: "dim" | "accent" | "amber" | "red";
  children: ReactNode;
  className?: string;
  glass?: boolean;
}) {
  return (
    <section
      className={`site-panel rounded-sm ${glass ? "site-glass" : ""} ${className}`}
    >
      {legend && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <Legend tone={tone}>{legend}</Legend>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

/** Horizontally scrollable readout. Wide instrument panels (tables, tree
    listings, transcripts) scroll inside their own box rather than widening the
    document. WCAG 2.1.1: a scrollable region must be reachable by keyboard, so
    it is a labelled region with a tab stop. The right-hand fade is the
    affordance that says "there is more this way". */
export function ScrollX({
  children,
  label,
  className = "",
  fade = "#0d141a",
}: {
  children: ReactNode;
  label: string;
  className?: string;
  fade?: string;
}) {
  return (
    <div className={`relative ${className}`}>
      <div
        role="region"
        aria-label={label}
        tabIndex={0}
        className="overflow-x-auto focus-visible:outline-offset-[-2px]"
      >
        {children}
      </div>
      <div
        aria-hidden
        className="pointer-events-none absolute inset-y-0 right-0 w-8"
        style={{
          background: `linear-gradient(to left, ${fade}, transparent)`,
        }}
      />
    </div>
  );
}

/* ----------------------------------------------------------------- actions */

type ButtonKind = "primary" | "default" | "quiet";

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-2 rounded-[3px] px-4 py-2.5 " +
  "text-[13px] font-medium transition-colors whitespace-nowrap";

const BUTTON_KIND: Record<ButtonKind, string> = {
  primary: "site-key site-key-lit text-accent hover:text-[#8bf5b8]",
  default:
    "site-key border border-line-2 text-ink hover:border-ink-faint hover:text-white",
  quiet:
    "border border-transparent text-ink-dim hover:text-ink hover:border-line-2",
};

export function ActionLink({
  href,
  kind = "default",
  children,
  external,
  className = "",
}: {
  href: string;
  kind?: ButtonKind;
  children: ReactNode;
  external?: boolean;
  className?: string;
}) {
  const cls = `${BUTTON_BASE} ${BUTTON_KIND[kind]} ${className}`;
  if (external) {
    return (
      <a href={href} className={cls} target="_blank" rel="noreferrer noopener">
        {children}
      </a>
    );
  }
  return (
    <Link href={href} className={cls}>
      {children}
    </Link>
  );
}

/* ------------------------------------------------------------------- misc */

/** Section heading block: index + legend + display headline + lede. */
export function SectionHead({
  index,
  legend,
  title,
  lede,
  tone = "accent",
  as = "h2",
  className = "",
}: {
  index?: string;
  legend: string;
  title: ReactNode;
  lede?: ReactNode;
  tone?: "dim" | "accent" | "amber" | "red";
  /** Page-level heads must be `h1`; every other head stays `h2`. */
  as?: "h1" | "h2";
  className?: string;
}) {
  const Heading = as;
  return (
    <div className={`max-w-[46rem] ${className}`}>
      <div className="flex items-center gap-3">
        {index && (
          <span className="site-mono text-[10px] text-ink-faint">{index}</span>
        )}
        <Legend tone={tone}>{legend}</Legend>
      </div>
      <Heading
        className={`site-display mt-4 font-semibold text-white ${
          as === "h1"
            ? "text-[clamp(2rem,6.4vw,3.5rem)]"
            : "text-[clamp(1.85rem,5.4vw,3rem)]"
        }`}
      >
        {title}
      </Heading>
      {lede && (
        <p className="site-lede mt-4 text-[15px] leading-relaxed text-ink-dim sm:text-[16px]">
          {lede}
        </p>
      )}
    </div>
  );
}

/** Small pill used for capability / status tagging. */
export function Tag({
  children,
  tone = "dim",
}: {
  children: ReactNode;
  tone?: "dim" | "accent" | "amber" | "red";
}) {
  const cls = {
    dim: "border-line-2 text-ink-faint",
    accent: "border-accent-dim bg-accent/10 text-accent",
    amber: "border-amber/40 bg-amber/10 text-amber",
    red: "border-red/40 bg-red/10 text-red",
  }[tone];
  return (
    <span
      className={`site-mono inline-flex items-center gap-1.5 rounded-sm border px-2 py-[3px] text-[10px] uppercase tracking-[0.1em] ${cls}`}
    >
      {children}
    </span>
  );
}

/** A labelled readout: tiny etched key over a monospace value. */
export function Readout({
  label,
  value,
  tone = "ink",
}: {
  label: string;
  value: ReactNode;
  tone?: "ink" | "accent" | "amber";
}) {
  const color = {
    ink: "text-ink",
    accent: "text-accent",
    amber: "text-amber",
  }[tone];
  return (
    <div className="flex flex-col gap-2">
      <Legend>{label}</Legend>
      <span className={`site-mono text-[15px] leading-none ${color}`}>
        {value}
      </span>
    </div>
  );
}

/** Check / cross / dash glyph used across the ledger and pricing tables. */
export function Glyph({ state }: { state: "yes" | "no" | "partial" }) {
  const spec = {
    yes: { g: "✓", cls: "text-accent", label: "included" },
    no: { g: "—", cls: "text-ink-faint", label: "not included" },
    partial: { g: "◐", cls: "text-amber", label: "partial" },
  }[state];
  return (
    <span className={`site-mono text-[13px] ${spec.cls}`} title={spec.label}>
      <span aria-hidden>{spec.g}</span>
      <span className="sr-only">{spec.label}</span>
    </span>
  );
}
