"use client";

/* Front-of-rack header. Sticky, translucent, hairline-bottomed. On small
   viewports the nav collapses into a disclosure panel — a real button with
   aria-expanded, closed by Escape and by navigating. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { ActionLink, Container, Led } from "./kit";

const NAV = [
  { href: "/docs", label: "How it works" },
  { href: "/pricing", label: "Pricing" },
  { href: "/about", label: "About" },
  { href: "/contact", label: "Contact" },
];

export function Mark({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 28 28"
      className={className}
      fill="none"
      aria-hidden
      focusable="false"
    >
      {/* package body */}
      <rect
        x="7.5"
        y="7.5"
        width="13"
        height="13"
        rx="1.5"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      {/* pin 1 dot */}
      <circle cx="10.6" cy="10.6" r="1.15" fill="currentColor" />
      {/* leads */}
      {[10.5, 14, 17.5].map((v) => (
        <g key={v} stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
          <line x1="3.4" y1={v} x2="7.5" y2={v} />
          <line x1="20.5" y1={v} x2="24.6" y2={v} />
          <line x1={v} y1="3.4" x2={v} y2="7.5" />
          <line x1={v} y1="20.5" x2={v} y2="24.6" />
        </g>
      ))}
    </svg>
  );
}

export function SiteHeader() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <header className="sticky top-0 z-50">
      <div className="border-b border-line/80 bg-[#0b0f14]/85 backdrop-blur-md">
        <Container wide>
          <div className="flex h-14 items-center justify-between gap-4">
            {/* ---------------------------------------------------- brand */}
            <Link
              href="/"
              className="group flex items-center gap-2.5"
              aria-label="EmbeddPilot — home"
            >
              <span className="relative flex h-7 w-7 items-center justify-center rounded-[3px] border border-line-2 bg-panel text-accent transition-colors group-hover:border-accent-dim">
                <Mark className="h-[18px] w-[18px]" />
              </span>
              <span className="flex flex-col leading-none">
                <span className="text-[14px] font-semibold tracking-[-0.01em] text-white">
                  EmbeddPilot
                </span>
                <span className="site-legend mt-[3px] hidden text-[8.5px] font-semibold uppercase tracking-[0.24em] text-ink-faint sm:block">
                  Verified in emulation
                </span>
              </span>
            </Link>

            {/* ------------------------------------------------------ nav */}
            <nav
              aria-label="Primary"
              className="hidden items-center gap-1 md:flex"
            >
              {NAV.map((item) => {
                const active = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`relative rounded-[3px] px-3 py-1.5 text-[13px] transition-colors ${
                      active
                        ? "text-accent"
                        : "text-ink-dim hover:bg-panel hover:text-ink"
                    }`}
                  >
                    {item.label}
                    {active && (
                      <span
                        aria-hidden
                        className="absolute inset-x-3 -bottom-[1px] h-[2px] bg-accent"
                        style={{ boxShadow: "0 0 8px #3fe081" }}
                      />
                    )}
                  </Link>
                );
              })}
            </nav>

            {/* --------------------------------------------------- action */}
            <div className="flex items-center gap-2">
              <div className="hidden sm:block">
                <ActionLink href="/" kind="primary" className="!py-2 !text-[12.5px]">
                  <Led tone="green" breathe />
                  Open the workspace
                </ActionLink>
              </div>
              <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                aria-controls="site-nav-panel"
                className="site-key flex h-9 w-9 items-center justify-center rounded-[3px] border border-line-2 text-ink-dim transition-colors hover:text-ink md:hidden"
              >
                <span className="sr-only">
                  {open ? "Close menu" : "Open menu"}
                </span>
                <svg
                  viewBox="0 0 20 20"
                  className="h-4 w-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  aria-hidden
                >
                  {open ? (
                    <>
                      <line x1="5" y1="5" x2="15" y2="15" />
                      <line x1="15" y1="5" x2="5" y2="15" />
                    </>
                  ) : (
                    <>
                      <line x1="3.5" y1="6.5" x2="16.5" y2="6.5" />
                      <line x1="3.5" y1="13.5" x2="16.5" y2="13.5" />
                    </>
                  )}
                </svg>
              </button>
            </div>
          </div>
        </Container>
      </div>

      {/* --------------------------------------------- disclosure (mobile) */}
      {open && (
        <div
          id="site-nav-panel"
          className="border-b border-line bg-[#0b0f14]/97 backdrop-blur-md md:hidden"
        >
          <Container wide>
            {/* any activation inside the panel is a navigation, so it closes */}
            <nav
              aria-label="Primary (mobile)"
              className="flex flex-col py-3"
              onClick={() => setOpen(false)}
            >
              {NAV.map((item) => {
                const active = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex items-center gap-3 border-b border-line/60 py-3 text-[14px] ${
                      active ? "text-accent" : "text-ink-dim"
                    }`}
                  >
                    <Led tone={active ? "green" : "off"} />
                    {item.label}
                  </Link>
                );
              })}
              <div className="pt-4">
                <ActionLink href="/app" kind="primary" className="w-full">
                  Open the workspace
                </ActionLink>
              </div>
            </nav>
          </Container>
        </div>
      )}
    </header>
  );
}
