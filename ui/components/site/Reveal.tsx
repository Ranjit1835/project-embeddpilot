"use client";

/* Scroll-triggered reveal. Deliberately restrained: a short rise and a fade,
   once, never replayed. Honours prefers-reduced-motion via the `useReducedMotion`
   hook so the content is simply present rather than animated. */

import { motion, useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";

const EASE = [0.22, 1, 0.36, 1] as const;

export function Reveal({
  children,
  delay = 0,
  y = 14,
  className = "",
  as = "div",
}: {
  children: ReactNode;
  delay?: number;
  y?: number;
  className?: string;
  as?: "div" | "section" | "li" | "span";
}) {
  const reduced = useReducedMotion();
  const M = motion[as];
  return (
    <M
      className={className}
      initial={reduced ? false : { opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.25, margin: "0px 0px -60px 0px" }}
      transition={{ duration: 0.55, ease: EASE, delay }}
    >
      {children}
    </M>
  );
}

/** Staggered children — pass `index` from a map. */
export function RevealItem({
  children,
  index,
  className = "",
  step = 0.07,
}: {
  children: ReactNode;
  index: number;
  className?: string;
  step?: number;
}) {
  return (
    <Reveal className={className} delay={Math.min(index * step, 0.42)}>
      {children}
    </Reveal>
  );
}
