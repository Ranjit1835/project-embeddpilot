import type { Metadata } from "next";
import {
  ActionLink,
  Container,
  Legend,
  Rule,
  SectionHead,
} from "@/components/site/kit";
import { ClaimBanner } from "@/components/site/panels";
import { Reveal } from "@/components/site/Reveal";

export const metadata: Metadata = {
  title: "About",
  description:
    "EmbeddPilot turns a plain-English requirement into embedded firmware whose behaviour is demonstrated by an emulated run. The principle: the generator is never the judge.",
};

const PRACTICE: { h: string; p: string }[] = [
  {
    h: "It asks before it assumes",
    p: "A requirement becomes clarifying questions, then a structured spec. No field is filled with a value that cannot be traced back to something you said.",
  },
  {
    h: "It reads the datasheet, not its memory",
    p: "Register addresses and device constants come from a cross-checked map extracted from the PDF. Ambiguity is flagged, not quietly resolved.",
  },
  {
    h: "It compiles, boots and asserts",
    p: "The generated repository is cross-compiled for ARM and booted on an emulated STM32F4. A harness the generator does not control asserts the UART output.",
  },
  {
    h: "It states its own limits",
    p: "Emulation is not silicon. That distinction is on the landing page, in the docs, and in the footer — because the moment it is blurred, the verification is worth nothing.",
  },
];

export default function AboutPage() {
  return (
    <>
      {/* =============================================================== head */}
      <section className="relative overflow-hidden border-b border-line">
        <div
          aria-hidden
          className="site-pcb site-pcb-fade pointer-events-none absolute inset-x-0 -top-20 h-[30rem]"
        />
        <Container wide className="relative">
          <div className="py-16 sm:py-24">
            <Reveal>
              <div className="max-w-[42rem]">
                <Legend tone="accent">About</Legend>
                <h1 className="site-display mt-5 text-[clamp(2rem,6.6vw,3.6rem)] font-semibold text-white">
                  A generator that is not allowed
                  <br className="hidden md:block" /> to grade its own work.
                </h1>
                <p className="site-lede mt-6 text-[15.5px] leading-relaxed text-ink-dim sm:text-[17px]">
                  EmbeddPilot turns a plain-English requirement into embedded
                  firmware, then makes that firmware run. The application it
                  writes is cross-compiled for ARM and booted on an emulated
                  STM32F4 against mocked devices, and a harness asserts the UART
                  output it produced. Behaviour is demonstrated, not described.
                </p>
              </div>
            </Reveal>
          </div>
        </Container>
      </section>

      {/* ========================================================== principle */}
      <section className="py-16 sm:py-20">
        <Container wide>
          <Reveal>
            <figure className="relative overflow-hidden rounded-sm border border-line bg-panel px-6 py-10 sm:px-10 sm:py-14">
              <span
                aria-hidden
                className="pointer-events-none absolute inset-y-0 left-0 w-1 bg-accent-dim"
              />
              <div
                aria-hidden
                className="site-pcb pointer-events-none absolute inset-0 opacity-40"
                style={{
                  maskImage:
                    "linear-gradient(100deg, transparent 40%, #000 100%)",
                  WebkitMaskImage:
                    "linear-gradient(100deg, transparent 40%, #000 100%)",
                }}
              />
              <blockquote className="relative">
                <Legend tone="accent">The principle</Legend>
                <p className="site-display mt-5 max-w-[24rem] text-[clamp(1.7rem,6vw,2.9rem)] font-semibold text-white">
                  The generator is never the judge.
                </p>
              </blockquote>
              <figcaption className="site-lede relative mt-6 max-w-[36rem] text-[14.5px] leading-relaxed text-ink-dim">
                The component that writes the driver is not permitted to decide
                whether the driver is correct. The generated library contains no
                test logic, no pass/fail strings and no diagnostic printing — a
                guard enforces that mechanically on every run. Every expectation
                lives in a harness the generator does not write. If a driver is
                wrong, nothing in the system is in a position to approve it.
              </figcaption>
            </figure>
          </Reveal>
        </Container>
      </section>

      {/* =========================================================== practice */}
      <section className="pb-16 sm:pb-20">
        <Container wide>
          <Reveal>
            <SectionHead
              legend="In practice"
              title="Four consequences of that one rule"
            />
          </Reveal>
          <Reveal delay={0.06}>
            <ol className="mt-10 grid gap-px overflow-hidden rounded-sm border border-line bg-line sm:grid-cols-2">
              {PRACTICE.map((c, i) => (
                <li key={c.h} className="bg-panel px-5 py-6 sm:px-6 sm:py-7">
                  <span className="site-mono text-[11px] text-ink-faint">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <h3 className="mt-3 text-[16px] font-semibold leading-snug text-white">
                    {c.h}
                  </h3>
                  <p className="site-lede mt-2.5 text-[13.5px] leading-relaxed text-ink-dim">
                    {c.p}
                  </p>
                </li>
              ))}
            </ol>
          </Reveal>
        </Container>
      </section>

      {/* ============================================================== claim */}
      <section className="pb-16 sm:pb-20">
        <Container wide>
          <div className="grid gap-10 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:items-center lg:gap-16">
            <Reveal className="min-w-0">
              <SectionHead
                legend="Scope"
                tone="amber"
                title="Emulation is the boundary"
                lede="Today EmbeddPilot targets one emulated MCU family over I2C and SPI, including multi-device systems. There is no path to a physical board, and no feature that predicts how the firmware will behave on one."
              />
            </Reveal>
            <Reveal delay={0.06} className="min-w-0">
              <ClaimBanner />
            </Reveal>
          </div>
        </Container>
      </section>

      {/* ================================================================ cta */}
      <section className="pb-8">
        <Container wide>
          <Rule />
          <div className="flex flex-col gap-6 py-14 sm:flex-row sm:items-center sm:justify-between">
            <p className="site-lede max-w-md text-[15px] leading-relaxed text-ink-dim">
              The fastest way to judge it is to give it a requirement and read
              the transcript it produces.
            </p>
            <div className="flex flex-col gap-3 sm:flex-row">
              <ActionLink href="/app" kind="primary">
                Open the workspace
              </ActionLink>
              <ActionLink href="/docs" kind="default">
                Read the docs
              </ActionLink>
            </div>
          </div>
        </Container>
      </section>
    </>
  );
}
