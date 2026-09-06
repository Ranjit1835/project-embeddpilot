"use client";

/* The evidence panel. This is the product's whole argument rendered as an
   instrument: a cross-compile, an emulated STM32F4 boot, and the UART the
   harness actually asserted against. Lines arrive in sequence, once.

   The transcript is representative of a real run, not live telemetry. */

import { motion, useReducedMotion } from "framer-motion";
import { Led, Legend } from "./kit";

type Seg = { t: string; c?: "dim" | "faint" | "accent" | "amber" | "white" };
type Line = { k: string; segs: Seg[] };

const COLOR: Record<NonNullable<Seg["c"]>, string> = {
  dim: "text-ink-dim",
  faint: "text-ink-faint",
  accent: "text-accent",
  amber: "text-amber",
  white: "text-white",
};

/* Lines are kept at or under ~46 monospace columns so the whole transcript is
   readable at 360px without needing to be scrolled. */
const LINES: Line[] = [
  {
    k: "cmd",
    segs: [
      { t: "$ ", c: "faint" },
      { t: "embeddpilot verify", c: "white" },
      { t: " --emu renode", c: "dim" },
    ],
  },
  { k: "gap1", segs: [] },
  {
    k: "s1",
    segs: [
      { t: "[1/6] ", c: "faint" },
      { t: "toolchain  ", c: "dim" },
      { t: "arm-none-eabi-gcc 13.2.0", c: "white" },
    ],
  },
  {
    k: "s2",
    segs: [
      { t: "[2/6] ", c: "faint" },
      { t: "compile    ", c: "dim" },
      { t: "src/main.c → app.elf", c: "white" },
    ],
  },
  {
    k: "s3",
    segs: [
      { t: "[3/6] ", c: "faint" },
      { t: "link       ", c: "dim" },
      { t: "stm32f405.ld · .text 3.1k", c: "white" },
    ],
  },
  {
    k: "s4",
    segs: [
      { t: "[4/6] ", c: "faint" },
      { t: "machine    ", c: "dim" },
      { t: "STM32F4 @ 168 MHz → main()", c: "white" },
    ],
  },
  {
    k: "s5",
    segs: [
      { t: "[5/6] ", c: "faint" },
      { t: "devices    ", c: "dim" },
      { t: "i2c1:0x77 · spi2:cs0", c: "white" },
      { t: " (mock)", c: "faint" },
    ],
  },
  { k: "gap2", segs: [] },
  {
    k: "u0",
    segs: [
      { t: "uart1 │ ", c: "faint" },
      { t: "EMBEDDPILOT BOOT", c: "accent" },
    ],
  },
  {
    k: "u1",
    segs: [
      { t: "uart1 │ ", c: "faint" },
      { t: "i2c1 probe 0x77 → id 0x55", c: "dim" },
      { t: "     OK", c: "accent" },
    ],
  },
  {
    k: "u2",
    segs: [
      { t: "uart1 │ ", c: "faint" },
      { t: "calib 22B → ac1=408", c: "dim" },
      { t: "           OK", c: "accent" },
    ],
  },
  {
    k: "u3",
    segs: [
      { t: "uart1 │ ", c: "faint" },
      { t: "temp raw 27898 → 15.0 C", c: "dim" },
      { t: "       OK", c: "accent" },
    ],
  },
  {
    k: "u4",
    segs: [
      { t: "uart1 │ ", c: "faint" },
      { t: "pres raw 23843 → 69964 Pa", c: "dim" },
      { t: "     OK", c: "accent" },
    ],
  },
  {
    k: "u5",
    segs: [
      { t: "uart1 │ ", c: "faint" },
      { t: "spi2 cs0 0x1900 → 25.00 C", c: "dim" },
      { t: "     OK", c: "accent" },
    ],
  },
  { k: "gap3", segs: [] },
  {
    k: "verdict",
    segs: [
      { t: "[6/6] ", c: "faint" },
      { t: "assert     ", c: "dim" },
      { t: "6/6 expectations · exit 0", c: "accent" },
    ],
  },
];

const STEP = 0.12;

export function BootConsole() {
  const reduced = useReducedMotion();

  return (
    <div className="site-chassis p-[7px]">
      {/* four fasteners on the rack ear */}
      <span
        className="pointer-events-none absolute left-[7px] top-[7px] h-1.5 w-1.5 rounded-full bg-[#3b4653] shadow-[inset_0_1px_0_rgba(255,255,255,0.3)]"
        aria-hidden
      />
      <span
        className="pointer-events-none absolute right-[7px] top-[7px] h-1.5 w-1.5 rounded-full bg-[#3b4653] shadow-[inset_0_1px_0_rgba(255,255,255,0.3)]"
        aria-hidden
      />

      <div className="site-glass relative overflow-hidden rounded-[4px] bg-[#0a1016] shadow-[inset_0_0_0_1px_#1e2833,inset_0_2px_18px_rgba(0,0,0,0.75)]">
        {/* ------------------------------------------------------ title bar */}
        <div className="relative z-20 flex items-center justify-between gap-3 border-b border-line bg-[#0e161d] px-3 py-2">
          <div className="flex min-w-0 items-center gap-2">
            <Led tone="green" breathe />
            <Legend className="truncate">Renode · STM32F4 · emulated</Legend>
          </div>
          <span className="site-mono shrink-0 text-[10px] text-ink-faint">
            run 0x1f3a
          </span>
        </div>

        {/* the scope sweep, behind the text */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 z-0 w-24 bg-gradient-to-r from-transparent via-accent/[0.07] to-transparent site-sweep"
        />

        {/* --------------------------------------------------------- output */}
        <div
          role="group"
          aria-label="Verification transcript"
          tabIndex={0}
          className="relative z-10 overflow-x-auto px-3 py-3.5 focus-visible:outline-offset-[-2px] sm:px-4 sm:py-4"
        >
          <div
            className="site-mono w-max text-[10.5px] leading-[1.75] sm:text-[11.5px] md:text-[12px]"
            role="img"
            aria-label="Representative EmbeddPilot verification transcript: toolchain arm-none-eabi-gcc, compile and link for STM32F405, emulated STM32F4 boot in Renode with mocked I2C and SPI devices, six UART expectations matched, exit code zero."
          >
            {LINES.map((line, i) =>
              line.segs.length === 0 ? (
                <div key={line.k} className="h-3" aria-hidden />
              ) : (
                <motion.div
                  key={line.k}
                  initial={reduced ? false : { opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{
                    duration: 0.28,
                    delay: reduced ? 0 : 0.25 + i * STEP,
                    ease: "easeOut",
                  }}
                  className="whitespace-pre"
                >
                  {line.segs.map((s, j) => (
                    <span key={j} className={COLOR[s.c ?? "dim"]}>
                      {s.t}
                    </span>
                  ))}
                </motion.div>
              )
            )}
            <motion.div
              initial={reduced ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: reduced ? 0 : 0.25 + LINES.length * STEP }}
              className="whitespace-pre"
            >
              <span className="text-ink-faint">$ </span>
              <span className="site-caret inline-block h-[1em] w-[0.55em] translate-y-[0.12em] bg-accent" />
            </motion.div>
          </div>
        </div>

        {/* ------------------------------------------------------ verdict bar */}
        <div className="relative z-20 flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 border-t border-line bg-[#0e161d] px-3 py-2">
          <div className="flex items-center gap-2">
            <Led tone="green" />
            <span className="site-mono text-[10.5px] uppercase tracking-[0.12em] text-accent">
              Emulation passed
            </span>
          </div>
          <span className="site-mono text-[10.5px] text-ink-faint">
            not hardware evidence
          </span>
        </div>
      </div>
    </div>
  );
}
