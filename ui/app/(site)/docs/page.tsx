import type { Metadata } from "next";
import { CapabilityLedger } from "@/components/site/CapabilityLedger";
import {
  ActionLink,
  Bay,
  Container,
  Led,
  Legend,
  Rule,
  SectionHead,
} from "@/components/site/kit";
import {
  ClaimBanner,
  ConflictReadout,
  PipelineLedger,
  RepoReadout,
  TargetSheet,
} from "@/components/site/panels";
import { Reveal } from "@/components/site/Reveal";

export const metadata: Metadata = {
  title: "How it works",
  description:
    "How EmbeddPilot goes from a plain-English requirement to firmware booted on an emulated STM32F4 — and precisely what a passing emulated run does and does not prove.",
};

const TOC = [
  { id: "pipeline", label: "The pipeline" },
  { id: "verified", label: "What is verified" },
  { id: "not-verified", label: "What is not verified" },
  { id: "targets", label: "Targets and buses" },
  { id: "output", label: "What you receive" },
  { id: "principle", label: "The principle" },
  { id: "ledger", label: "Capability ledger" },
];

const VERIFIED: string[] = [
  "The generated repository cross-compiles with arm-none-eabi for the target.",
  "The ELF links successfully against the supplied linker script.",
  "The firmware boots on an emulated STM32F4 in Renode and reaches application code.",
  "Every register the driver touches exists in the register map extracted from the datasheet.",
  "The device interaction sequence produces exactly the UART output the harness expects — byte for byte.",
  "No two devices in the composed system claim the same pin function, I2C address, DMA stream or IRQ line.",
  "The run terminates with a real exit code. A failure is reported as a failure.",
];

const NOT_VERIFIED: string[] = [
  "Behaviour on physical silicon. Nothing here has touched a board.",
  "Real-world timing: clock accuracy, bus setup and hold margins, interrupt latency under load.",
  "Electrical behaviour: pull-up sizing, logic levels, noise immunity, power sequencing, brown-out.",
  "Part-to-part variance, silicon errata, and anything absent from the datasheet PDF that was read.",
  "Long-run stability, thermal drift, EMC, or mechanical assembly.",
  "The fidelity of the mocked devices themselves — they answer the protocol, they do not simulate physics.",
];

function VerdictList({
  items,
  tone,
}: {
  items: string[];
  tone: "accent" | "amber";
}) {
  const accent = tone === "accent";
  return (
    <ul className="divide-y divide-line/60">
      {items.map((t) => (
        <li key={t} className="flex items-start gap-3 px-4 py-3.5 sm:px-5">
          <span
            aria-hidden
            className={`site-mono mt-[2px] shrink-0 text-[13px] ${
              accent ? "text-accent" : "text-amber"
            }`}
          >
            {accent ? "✓" : "✕"}
          </span>
          <span className="site-lede text-[14px] leading-relaxed text-ink-dim">
            {t}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Section({
  id,
  children,
}: {
  id: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24 py-14 first:pt-0 sm:py-16">
      {children}
    </section>
  );
}

export default function DocsPage() {
  return (
    <>
      {/* =============================================================== head */}
      <section className="relative overflow-hidden border-b border-line">
        <div
          aria-hidden
          className="site-pcb site-pcb-fade pointer-events-none absolute inset-x-0 -top-20 h-[30rem]"
        />
        <Container wide className="relative">
          <div className="py-16 sm:py-20">
            <Reveal>
              <SectionHead
                as="h1"
                legend="Documentation"
                title="How it works, and what a passing run actually proves"
                lede="EmbeddPilot is a pipeline with a hard gate at the end: the firmware is compiled and made to run. This page describes each stage, then draws the line between what the emulated run establishes and what it cannot."
              />
            </Reveal>
            <Reveal delay={0.08} className="mt-8">
              <ClaimBanner />
            </Reveal>
          </div>
        </Container>
      </section>

      <Container wide>
        <div className="grid gap-10 py-14 lg:grid-cols-[15rem_minmax(0,1fr)] lg:gap-14">
          {/* ------------------------------------------------------- index */}
          <aside className="min-w-0 lg:sticky lg:top-24 lg:self-start">
            <Legend>Contents</Legend>
            <nav aria-label="On this page" className="mt-4">
              <ol className="flex flex-col">
                {TOC.map((t, i) => (
                  <li key={t.id}>
                    <a
                      href={`#${t.id}`}
                      className="flex items-baseline gap-3 border-l border-line py-2 pl-3 text-[13px] text-ink-dim transition-colors hover:border-accent-dim hover:text-accent"
                    >
                      <span className="site-mono text-[10px] text-ink-faint">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      {t.label}
                    </a>
                  </li>
                ))}
              </ol>
            </nav>
          </aside>

          {/* ------------------------------------------------------- body */}
          <div className="min-w-0">
            <Section id="pipeline">
              <Reveal>
                <SectionHead
                  index="01"
                  legend="Pipeline"
                  title="Six stages"
                  lede="Each stage produces an artefact the next stage consumes. When a stage cannot establish something, it says so instead of letting the next stage improvise."
                />
              </Reveal>
              <PipelineLedger />
              <div className="mt-10">
                <Reveal>
                  <ConflictReadout />
                </Reveal>
              </div>
            </Section>

            <Rule />

            <Section id="verified">
              <Reveal>
                <SectionHead
                  index="02"
                  legend="Verified"
                  title="What a passing emulated run establishes"
                  lede="These are claims the run itself demonstrates. If any of them were false, the run would fail and you would see it."
                />
              </Reveal>
              <Reveal delay={0.06} className="mt-8">
                <Bay
                  legend="Established by the run"
                  tone="accent"
                  right={
                    <span className="flex items-center gap-2">
                      <Led tone="green" breathe />
                      <span className="site-mono text-[10px] text-accent">
                        exit 0
                      </span>
                    </span>
                  }
                >
                  <VerdictList items={VERIFIED} tone="accent" />
                </Bay>
              </Reveal>
            </Section>

            <Rule />

            <Section id="not-verified">
              <Reveal>
                <SectionHead
                  index="03"
                  legend="Not verified"
                  tone="amber"
                  title="What it says nothing about"
                  lede="An emulator answers the protocol. It does not model the physical world. Treat a passing run as a strong signal that the logic is right, and as no signal at all about the board."
                />
              </Reveal>
              <Reveal delay={0.06} className="mt-8">
                <Bay
                  legend="Outside the emulator"
                  tone="amber"
                  right={
                    <span className="flex items-center gap-2">
                      <Led tone="amber" />
                      <span className="site-mono text-[10px] text-amber">
                        unproven
                      </span>
                    </span>
                  }
                >
                  <VerdictList items={NOT_VERIFIED} tone="amber" />
                </Bay>
              </Reveal>
              <Reveal delay={0.1}>
                <p className="site-lede mt-6 text-[14px] leading-relaxed text-ink-dim">
                  There is deliberately no feature that predicts hardware
                  success. Flashing to a physical board and hardware-in-the-loop
                  verification are{" "}
                  <span className="text-amber">not built yet</span>; they are on
                  the roadmap and are labelled as such everywhere they appear on
                  this site.
                </p>
              </Reveal>
            </Section>

            <Rule />

            <Section id="targets">
              <Reveal>
                <SectionHead
                  index="04"
                  legend="Support"
                  title="Targets and buses"
                  lede="One emulated MCU family, two buses, and multi-device systems across them."
                />
              </Reveal>
              <Reveal delay={0.06} className="mt-8">
                <TargetSheet />
              </Reveal>
            </Section>

            <Rule />

            <Section id="output">
              <Reveal>
                <SectionHead
                  index="05"
                  legend="Deliverable"
                  title="What you receive"
                  lede="The same tree the emulator built and booted — application, generated driver, build system, linker script, README."
                />
              </Reveal>
              <Reveal delay={0.06} className="mt-8">
                <RepoReadout />
              </Reveal>
            </Section>

            <Rule />

            <Section id="principle">
              <Reveal>
                <SectionHead
                  index="06"
                  legend="Principle"
                  title="The generator is never the judge"
                  lede="The component that writes the driver is not allowed to decide whether the driver is correct."
                />
              </Reveal>
              <Reveal delay={0.06}>
                <div className="mt-8 grid gap-5 md:grid-cols-2">
                  {[
                    {
                      h: "The driver contains no test logic",
                      p: "No assertions, no pass/fail strings, no diagnostic printing. It is a library. A guard enforces this mechanically on every pipeline run.",
                    },
                    {
                      h: "The harness owns every expectation",
                      p: "Expected values and test scenarios live outside the generated code, so a wrong driver cannot also write the test that approves it.",
                    },
                    {
                      h: "Constants come from the register map",
                      p: "Device constants are read from the extracted map rather than recalled. Change a value in the map and the emitted code changes with it.",
                    },
                    {
                      h: "The same input produces the same output",
                      p: "Generation is deterministic. Two runs of the same spec produce the same repository, so a passing run stays meaningful.",
                    },
                  ].map((c) => (
                    <article
                      key={c.h}
                      className="site-panel rounded-sm px-5 py-5"
                    >
                      <h3 className="text-[15px] font-semibold leading-snug text-white">
                        {c.h}
                      </h3>
                      <p className="site-lede mt-2.5 text-[13.5px] leading-relaxed text-ink-dim">
                        {c.p}
                      </p>
                    </article>
                  ))}
                </div>
              </Reveal>
            </Section>

            <Rule />

            <Section id="ledger">
              <Reveal>
                <SectionHead
                  index="07"
                  legend="Ledger"
                  title="Shipped, and not shipped"
                  lede="The complete list, both halves."
                />
              </Reveal>
              <Reveal delay={0.06} className="mt-8">
                <CapabilityLedger />
              </Reveal>
            </Section>

            <Rule />

            <div className="flex flex-col gap-4 py-14 sm:flex-row sm:items-center sm:justify-between">
              <p className="site-lede max-w-md text-[14px] leading-relaxed text-ink-dim">
                Something here unclear, or contradicted by what the product
                actually did? That is a bug — report it.
              </p>
              <div className="flex flex-col gap-3 sm:flex-row">
                <ActionLink href="/" kind="primary">
                  Open the workspace
                </ActionLink>
                <ActionLink href="/contact" kind="default">
                  Contact
                </ActionLink>
              </div>
            </div>
          </div>
        </div>
      </Container>
    </>
  );
}
