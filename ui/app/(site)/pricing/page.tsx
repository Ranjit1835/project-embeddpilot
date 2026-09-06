import type { Metadata } from "next";
import { Fragment } from "react";
import {
  ActionLink,
  Bay,
  Container,
  Glyph,
  Led,
  Legend,
  Rule,
  ScrollX,
  SectionHead,
} from "@/components/site/kit";
import { ClaimBanner } from "@/components/site/panels";
import { Reveal, RevealItem } from "@/components/site/Reveal";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "EmbeddPilot pricing: Free at $0/mo with three generated applications a month, Pro at $29/mo for unlimited multi-device generation with SPI and repo export, and Enterprise for self-hosted deployments.",
};

type Tier = {
  id: string;
  name: string;
  price: string;
  cadence?: string;
  pitch: string;
  cta: { label: string; href: string; kind: "primary" | "default" };
  featured?: boolean;
  includes: string[];
  limits?: string[];
};

const TIERS: Tier[] = [
  {
    id: "free",
    name: "Free",
    price: "$0",
    cadence: "/ month",
    pitch:
      "Enough to put the claim to the test: generate an application, watch it boot in the emulator, read the assertions.",
    cta: { label: "Open the workspace", href: "/", kind: "default" },
    includes: [
      "3 generated applications per month",
      "Emulation verification on every generation",
      "I2C devices",
      "Clarifying-question intake and structured spec",
      "Resource conflict detection",
    ],
    limits: ["Single-device systems", "No repo export"],
  },
  {
    id: "pro",
    name: "Pro",
    price: "$29",
    cadence: "/ month",
    featured: true,
    pitch:
      "For building real multi-device systems: unlimited generations, both buses, and the complete repository on disk.",
    cta: { label: "Open the workspace", href: "/", kind: "primary" },
    includes: [
      "Unlimited generated applications",
      "Multi-device systems",
      "I2C and SPI devices",
      "Complete repo export — src, drivers, Makefile, linker script",
      "Priority generation queue",
      "Everything in Free",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: "Contact us",
    pitch:
      "For teams that cannot send datasheets to a hosted service, or who need the verification step to eventually reach real boards.",
    cta: { label: "Contact us", href: "/contact", kind: "default" },
    includes: [
      "On-premises / self-hosted deployment",
      "Hardware-in-the-loop verification (roadmap — not built yet)",
      "Support SLA",
      "Everything in Pro",
    ],
  },
];

type Row = {
  label: string;
  free: "yes" | "no" | "partial" | string;
  pro: "yes" | "no" | "partial" | string;
  ent: "yes" | "no" | "partial" | string;
};

const MATRIX: { group: string; rows: Row[] }[] = [
  {
    group: "Generation",
    rows: [
      { label: "Generated applications", free: "3 / month", pro: "unlimited", ent: "unlimited" },
      { label: "Clarifying-question intake", free: "yes", pro: "yes", ent: "yes" },
      { label: "Datasheet → verified register map", free: "yes", pro: "yes", ent: "yes" },
      { label: "Priority generation queue", free: "no", pro: "yes", ent: "yes" },
    ],
  },
  {
    group: "Systems",
    rows: [
      { label: "I2C devices", free: "yes", pro: "yes", ent: "yes" },
      { label: "SPI devices", free: "no", pro: "yes", ent: "yes" },
      { label: "Multi-device composition", free: "no", pro: "yes", ent: "yes" },
      { label: "Resource conflict detection", free: "yes", pro: "yes", ent: "yes" },
    ],
  },
  {
    group: "Verification",
    rows: [
      { label: "Emulated STM32F4 boot (Renode)", free: "yes", pro: "yes", ent: "yes" },
      { label: "UART assertion report", free: "yes", pro: "yes", ent: "yes" },
      { label: "Hardware-in-the-loop", free: "no", pro: "no", ent: "roadmap" },
    ],
  },
  {
    group: "Delivery",
    rows: [
      { label: "Complete repo export", free: "no", pro: "yes", ent: "yes" },
      { label: "Self-hosted / on-prem", free: "no", pro: "no", ent: "yes" },
      { label: "Support SLA", free: "no", pro: "no", ent: "yes" },
    ],
  },
];

function Cell({ v }: { v: string }) {
  if (v === "yes" || v === "no" || v === "partial") {
    return <Glyph state={v} />;
  }
  return (
    <span
      className={`site-mono text-[11.5px] ${
        v === "roadmap" ? "text-amber" : "text-ink"
      }`}
    >
      {v}
    </span>
  );
}

const NOTES: { q: string; a: string }[] = [
  {
    q: "What counts as one generated application?",
    a: "One run of the full pipeline — requirement through spec, register map, composition, repository and emulated boot. Re-running verification on an unchanged spec does not consume another.",
  },
  {
    q: "What does 'emulation verification' actually include?",
    a: "The firmware is cross-compiled with arm-none-eabi, booted on an emulated STM32F4 in Renode against mocked devices, and its UART output is asserted against expectations the harness owns. You see the transcript and the exit code.",
  },
  {
    q: "Does any tier verify on physical hardware?",
    a: "No. No tier flashes a board today. Hardware-in-the-loop is on the Enterprise roadmap and is labelled as such everywhere it appears.",
  },
  {
    q: "Why is SPI a paid feature when it already works?",
    a: "SPI is shipped and exercised in emulation. It sits behind Pro because multi-device SPI systems are where the generation and verification cost concentrates.",
  },
];

export default function PricingPage() {
  return (
    <>
      {/* =============================================================== head */}
      <section className="relative overflow-hidden border-b border-line">
        <div
          aria-hidden
          className="site-pcb site-pcb-fade pointer-events-none absolute inset-x-0 -top-20 h-[32rem]"
        />
        <Container wide className="relative">
          <div className="py-16 sm:py-20">
            <Reveal>
              <SectionHead
                as="h1"
                legend="Pricing"
                title="Priced by how much you generate, not by how much we claim"
                lede="Every tier runs the same verification. The difference is volume, bus coverage and whether you get the repository on disk."
              />
            </Reveal>
            <Reveal delay={0.08}>
              <div className="mt-7 flex items-start gap-2.5 rounded-sm border border-line-2 bg-panel px-4 py-3">
                <span className="mt-[3px]">
                  <Led tone="cyan" />
                </span>
                <p className="site-mono text-[11.5px] leading-relaxed text-ink-dim">
                  Placeholder pricing. These numbers are provisional and will be
                  revised before general availability. No discount clock, no
                  limited-time offer.
                </p>
              </div>
            </Reveal>
          </div>
        </Container>
      </section>

      {/* ============================================================== tiers */}
      <section className="py-14 sm:py-16">
        <Container wide>
          <div className="grid gap-5 lg:grid-cols-3 lg:items-start">
            {TIERS.map((t, i) => (
              <RevealItem key={t.id} index={i} className="min-w-0">
                <article
                  className={`site-panel relative flex h-full flex-col rounded-sm ${
                    t.featured
                      ? "shadow-[inset_0_0_0_1px_var(--color-accent-dim),0_24px_60px_-40px_rgba(63,224,129,0.55)]"
                      : ""
                  }`}
                >
                  {t.featured && (
                    <span
                      aria-hidden
                      className="absolute inset-x-0 top-0 h-px bg-accent"
                      style={{ boxShadow: "0 0 12px #3fe081" }}
                    />
                  )}

                  <header className="border-b border-line px-5 py-5">
                    <div className="flex items-center gap-2.5">
                      <Led tone={t.featured ? "green" : "off"} breathe={t.featured} />
                      <Legend tone={t.featured ? "accent" : "dim"}>
                        {t.name}
                      </Legend>
                    </div>
                    <p className="mt-4 flex items-baseline gap-2">
                      <span
                        className={`site-mono text-[clamp(1.9rem,6vw,2.5rem)] leading-none ${
                          t.featured ? "text-accent" : "text-white"
                        }`}
                      >
                        {t.price}
                      </span>
                      {t.cadence && (
                        <span className="site-mono text-[12px] text-ink-faint">
                          {t.cadence}
                        </span>
                      )}
                    </p>
                    <p className="site-lede mt-4 text-[13.5px] leading-relaxed text-ink-dim">
                      {t.pitch}
                    </p>
                  </header>

                  <div className="flex flex-1 flex-col px-5 py-5">
                    <Legend>Includes</Legend>
                    <ul className="mt-4 flex flex-col gap-2.5">
                      {t.includes.map((f) => (
                        <li
                          key={f}
                          className="flex items-start gap-2.5 text-[13.5px] leading-relaxed text-ink"
                        >
                          <span
                            className="site-mono mt-[1px] shrink-0 text-accent"
                            aria-hidden
                          >
                            ✓
                          </span>
                          <span className="site-break">{f}</span>
                        </li>
                      ))}
                    </ul>

                    {t.limits && (
                      <>
                        <div className="my-5">
                          <Rule />
                        </div>
                        <Legend>Not included</Legend>
                        <ul className="mt-4 flex flex-col gap-2.5">
                          {t.limits.map((f) => (
                            <li
                              key={f}
                              className="flex items-start gap-2.5 text-[13.5px] leading-relaxed text-ink-faint"
                            >
                              <span className="site-mono mt-[1px] shrink-0" aria-hidden>
                                —
                              </span>
                              <span className="site-break">{f}</span>
                            </li>
                          ))}
                        </ul>
                      </>
                    )}

                    <div className="mt-7 pt-1">
                      <ActionLink
                        href={t.cta.href}
                        kind={t.cta.kind}
                        className="w-full"
                      >
                        {t.cta.label}
                      </ActionLink>
                    </div>
                  </div>
                </article>
              </RevealItem>
            ))}
          </div>
        </Container>
      </section>

      {/* ============================================================ matrix */}
      <section className="py-14 sm:py-16">
        <Container wide>
          <Reveal>
            <SectionHead
              index="§"
              legend="Comparison"
              title="Line by line"
              lede="Roadmap items are marked in amber and are not available on any tier today."
            />
          </Reveal>

          <Reveal delay={0.06} className="mt-8">
            <Bay legend="Tier matrix">
              <ScrollX label="Tier comparison table — scroll horizontally to see every tier">
                <table className="w-full min-w-[34rem] border-collapse text-left">
                  <caption className="sr-only">
                    Feature comparison across the Free, Pro and Enterprise tiers
                  </caption>
                  <thead>
                    <tr className="border-b border-line">
                      <th
                        scope="col"
                        className="site-legend px-4 py-3 text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint"
                      >
                        Capability
                      </th>
                      {["Free", "Pro", "Enterprise"].map((h) => (
                        <th
                          key={h}
                          scope="col"
                          className={`site-legend w-[7.5rem] px-4 py-3 text-[10px] font-semibold uppercase tracking-[0.2em] ${
                            h === "Pro" ? "text-accent" : "text-ink-faint"
                          }`}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {MATRIX.map((g) => (
                      <Fragment key={g.group}>
                        <tr className="bg-panel-2/60">
                          <th
                            scope="colgroup"
                            colSpan={4}
                            className="site-legend border-y border-line px-4 py-2 text-left text-[10px] font-semibold uppercase tracking-[0.22em] text-ink-dim"
                          >
                            {g.group}
                          </th>
                        </tr>
                        {g.rows.map((r) => (
                          <tr
                            key={r.label}
                            className="border-b border-line/50 last:border-b-0"
                          >
                            <th
                              scope="row"
                              className="px-4 py-3 text-left text-[13.5px] font-normal text-ink"
                            >
                              {r.label}
                            </th>
                            <td className="px-4 py-3">
                              <Cell v={r.free} />
                            </td>
                            <td className="bg-accent/[0.03] px-4 py-3">
                              <Cell v={r.pro} />
                            </td>
                            <td className="px-4 py-3">
                              <Cell v={r.ent} />
                            </td>
                          </tr>
                        ))}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </ScrollX>
            </Bay>
          </Reveal>
        </Container>
      </section>

      {/* ============================================================= notes */}
      <section className="py-14 sm:py-16">
        <Container wide>
          <div className="grid gap-12 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] lg:gap-16">
            <Reveal className="min-w-0">
              <SectionHead
                legend="Fine print"
                title="What you are actually buying"
              />
              <div className="mt-8">
                <ClaimBanner />
              </div>
            </Reveal>

            <Reveal delay={0.06} className="min-w-0">
              <dl className="divide-y divide-line/60 border-y border-line/60">
                {NOTES.map((n) => (
                  <div key={n.q} className="py-5">
                    <dt className="text-[15px] font-medium leading-snug text-white">
                      {n.q}
                    </dt>
                    <dd className="site-lede mt-2 text-[13.5px] leading-relaxed text-ink-dim">
                      {n.a}
                    </dd>
                  </div>
                ))}
              </dl>
              <p className="mt-6 text-[13.5px] text-ink-dim">
                Something not covered here?{" "}
                <a
                  href="mailto:ranjitperumala@gmail.com"
                  className="site-break text-accent underline decoration-accent-dim underline-offset-4 hover:decoration-accent"
                >
                  ranjitperumala@gmail.com
                </a>
              </p>
            </Reveal>
          </div>
        </Container>
      </section>
    </>
  );
}
