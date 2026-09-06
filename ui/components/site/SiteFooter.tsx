/* Rear panel: rating plate, ports, serial. The honest claim lives here as
   permanently as it does on the landing page. */

import Link from "next/link";
import { Container, Legend, Rule } from "./kit";
import { Mark } from "./SiteHeader";

const GITHUB_ISSUES = "https://github.com/Ranjit1835/project-embeddpilot/issues";
const EMAIL = "ranjitperumala@gmail.com";

const COLUMNS: { legend: string; links: { href: string; label: string; external?: boolean }[] }[] =
  [
    {
      legend: "Product",
      links: [
        { href: "/", label: "Workspace" },
        { href: "/docs", label: "How it works" },
        { href: "/pricing", label: "Pricing" },
      ],
    },
    {
      legend: "Company",
      links: [
        { href: "/about", label: "About" },
        { href: "/contact", label: "Contact" },
      ],
    },
    {
      legend: "Support",
      links: [
        { href: GITHUB_ISSUES, label: "GitHub issues", external: true },
        { href: `mailto:${EMAIL}`, label: EMAIL, external: true },
      ],
    },
  ];

export function SiteFooter() {
  return (
    <footer className="relative z-10 mt-24 border-t border-line bg-[#090d11]">
      <Container wide>
        <div className="grid gap-10 py-14 md:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,0.7fr))] md:gap-8">
          {/* ------------------------------------------------ rating plate */}
          <div className="max-w-sm">
            <div className="flex items-center gap-2.5">
              <span className="flex h-7 w-7 items-center justify-center rounded-[3px] border border-line-2 bg-panel text-accent">
                <Mark className="h-[18px] w-[18px]" />
              </span>
              <span className="text-[14px] font-semibold text-white">
                EmbeddPilot
              </span>
            </div>
            <p className="site-lede mt-4 text-[13px] leading-relaxed text-ink-dim">
              A requirement becomes firmware, and the firmware is made to run.
              Behaviour is demonstrated by an emulated boot, not asserted by a
              model.
            </p>
            <p className="site-mono mt-4 text-[11px] leading-relaxed text-ink-faint">
              Verified in emulation — not evidence it works on physical silicon.
            </p>
          </div>

          {/* ------------------------------------------------------ columns */}
          {COLUMNS.map((col) => (
            <nav key={col.legend} aria-label={col.legend}>
              <Legend>{col.legend}</Legend>
              <ul className="mt-4 flex flex-col gap-2.5">
                {col.links.map((l) => (
                  <li key={l.label}>
                    {l.external ? (
                      <a
                        href={l.href}
                        target={l.href.startsWith("mailto:") ? undefined : "_blank"}
                        rel="noreferrer noopener"
                        className="site-break text-[13px] text-ink-dim transition-colors hover:text-accent"
                      >
                        {l.label}
                      </a>
                    ) : (
                      <Link
                        href={l.href}
                        className="text-[13px] text-ink-dim transition-colors hover:text-accent"
                      >
                        {l.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>

        <Rule />

        <div className="flex flex-col gap-3 py-6 sm:flex-row sm:items-center sm:justify-between">
          <p className="site-mono text-[11px] text-ink-faint">
            © {new Date().getFullYear()} EmbeddPilot
          </p>
          <p className="site-mono text-[11px] text-ink-faint">
            Target: STM32F4 (emulated, Renode) · I2C · SPI
          </p>
        </div>
      </Container>
    </footer>
  );
}
