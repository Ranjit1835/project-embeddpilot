"use client";

/* A compact per-check results strip for the V2 workspace.

   HONESTY CONTRACT
   ----------------
   * Uses `railFrom` from lib/v2-view.ts verbatim — no mapping logic here.
   * All four backend check states are visually distinct:
       pass          green  ✓
       fail          red    ✕
       not_applicable cyan  –   (nothing to check — NOT a pass)
       skipped       amber  ⊘   (could not run — still unknown — NOT a pass)
   * `skipped` always shows its backend note. If emulation comes back skipped,
     the user sees that immediately rather than a green aggregate hiding it.
   * Renders only what the backend sent. No invented checks, no defaults. */

import type { RailItem, RailState } from "../../lib/v2-view";

/* ---------------------------------------------------------------- glyph / colour

   These match the LED_COLOR palette from components/resource-map/chrome.tsx so
   the strip reads as the same instrument vocabulary as the resource map rail.
   RAIL_STYLE is documented at v2-view.ts:414 — the convention lives here. */

const GLYPH: Record<RailState, string> = {
  pass: "✓",
  fail: "✕",
  not_applicable: "–",
  skipped: "⊘",
  running: "…",
  pending: "·",
};

// Hex values taken directly from LED_COLOR in chrome.tsx
const STATE_COLOR: Record<RailState, string> = {
  pass: "#3fe081",       // phosphor green — checked, no findings
  fail: "#e5533c",       // alarm red — conflict reported
  not_applicable: "#2e88ad", // cyan — nothing to check (distinct from pass)
  skipped: "#e0a63c",   // amber — could not run, still unknown
  running: "#3fe081",    // green pulse — in flight
  pending: "#4d5a68",    // ink-faint — not reached
};

interface CheckStripProps {
  items: RailItem[];
}

export function CheckStrip({ items }: CheckStripProps) {
  if (!items.length) return null;

  return (
    <div
      role="list"
      aria-label="Check results"
      className="flex shrink-0 flex-wrap gap-x-3 gap-y-1 border-t border-line px-4 py-2"
    >
      {items.map((item) => (
        <CheckPill key={item.id} item={item} />
      ))}
    </div>
  );
}

function CheckPill({ item }: { item: RailItem }) {
  const color = STATE_COLOR[item.state];
  const glyph = GLYPH[item.state];

  return (
    <div
      role="listitem"
      className="flex items-center gap-1.5"
      title={item.note}
      aria-label={`${item.label}: ${item.state} — ${item.note}`}
    >
      {/* state glyph — the colour is the entire signal, never just the shape */}
      <span
        className="font-mono text-[11px] font-bold leading-none"
        style={{ color }}
        aria-hidden
      >
        {glyph}
      </span>

      {/* check label */}
      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-dim">
        {item.label}
      </span>

      {/* note — always shown for skipped so a hidden emulation failure cannot
          be disguised by a green aggregate banner. For other states it shows
          as a quieter inline annotation. */}
      <span
        className="font-mono text-[10px] leading-none"
        style={{
          color:
            item.state === "skipped" || item.state === "fail"
              ? color
              : "var(--color-ink-faint)",
        }}
      >
        {item.note}
      </span>
    </div>
  );
}
