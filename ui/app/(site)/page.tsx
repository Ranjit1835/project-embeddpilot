import type { Metadata } from "next";
import { BootConsole } from "@/components/site/BootConsole";
import { CapabilityLedger } from "@/components/site/CapabilityLedger";
import {
  ActionLink,
  Container,
  Legend,
  Rule,
  SectionHead,
} from "@/components/site/kit";
import {
  ClaimBanner,
  ConflictReadout,
  PipelineLedger,
  ProofStrip,
  RepoReadout,
  TargetSheet,
} from "@/components/site/panels";
import { Reveal } from "@/components/site/Reveal";

export const metadata: Metadata = {
  // absolute: this page is the site root, so it must not take the "— EmbeddPilot" suffix
  title: { absolute: "EmbeddPilot — firmware proven by running it" },
  description:
    "Describe an embedded device in plain English. EmbeddPilot writes a complete buildable repository, cross-compiles it for ARM and boots it on an emulated STM32F4, asserting the UART output it produces.",
};

const HERO_CHIPS = [
  "no invented register values",
  "conflict-checked composition",
  "a repo you can build",
];

export default function HomePage() {
  return (
    <>
      {/* =============================================================== hero */}
      <section className="relative overflow-hidden">
        <div
          aria-hidden
          className="site-pcb site-pcb-fade pointer-events-none absolute inset-x-0 -top-24 h-[46rem]"
        />
        <Container wide className="relative">
          <div className="grid items-center gap-12 py-16 sm:py-20 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.02fr)] lg:gap-14 lg:py-28">
            {/* ------------------------------------------------------ copy */}
            <div className="min-w-0">
              <Reveal>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                  <Legend tone="accent">Requirement</Legend>
                  <span className="site-mono text-[10px] text-ink-faint">→</span>
                  <Legend>Spec</Legend>
                  <span className="site-mono text-[10px] text-ink-faint">→</span>
                  <Legend>Driver</Legend>
                  <span className="site-mono text-[10px] text-ink-faint">→</span>
                  <Legend>Emulated boot</Legend>
                </div>
              </Reveal>

              <Reveal delay={0.06}>
                <h1 className="site-display mt-6 text-[clamp(2.15rem,7.4vw,4.4rem)] font-semibold text-white">
                  Firmware proven by
                  <br className="hidden sm:block" />{" "}
                  <span className="text-accent site-glow">running it.</span>
                </h1>
              </Reveal>

              <Reveal delay={0.12}>
                <p className="site-lede mt-6 max-w-[34rem] text-[15.5px] leading-relaxed text-ink-dim sm:text-[17px]">
                  Describe the device in plain English. EmbeddPilot asks until
                  the requirement is unambiguous, writes a complete embedded
                  repository, cross-compiles it for ARM and boots it on an
                  emulated STM32F4 — then asserts the UART output it actually
                  produced. The evidence is the run, not the prose.
                </p>
              </Reveal>

              <Reveal delay={0.18}>
                <p className="site-mono mt-5 max-w-[34rem] border-l-2 border-amber/50 pl-3.5 text-[12.5px] leading-relaxed text-amber">
                  Verified in emulation — not evidence it works on physical
                  silicon.
                </p>
              </Reveal>

              <Reveal delay={0.24}>
                <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
                  <ActionLink href="/app" kind="primary" className="sm:!px-5">
                    Open the workspace
                  </ActionLink>
                  <ActionLink href="/docs" kind="default">
                    See exactly what it verifies
                  </ActionLink>
                </div>
              </Reveal>

              <Reveal delay={0.3}>
                <ul className="mt-8 flex flex-wrap gap-x-5 gap-y-2">
                  {HERO_CHIPS.map((c) => (
                    <li
                      key={c}
                      className="site-mono flex items-center gap-2 text-[11.5px] text-ink-faint"
                    >
                      <span className="text-accent" aria-hidden>
                        ✓
                      </span>
                      {c}
                    </li>
                  ))}
                </ul>
              </Reveal>
            </div>

            {/* --------------------------------------------------- evidence */}
            <Reveal delay={0.12} className="min-w-0">
              <BootConsole />
            </Reveal>
          </div>
        </Container>

        <ProofStrip />
      </section>

      {/* ======================================================== pipeline */}
      <section className="py-20 sm:py-24">
        <Container wide>
          <Reveal>
            <SectionHead
              index="§1"
              legend="The pipeline"
              title="Six stages, and the last one is not optional"
              lede="Every stage hands the next one something it can check. Nothing downstream is allowed to invent what an earlier stage failed to establish."
            />
          </Reveal>
          <PipelineLedger />
        </Container>
      </section>

      {/* ======================================================= conflicts */}
      <section className="py-20 sm:py-24">
        <Container wide>
          <div className="grid gap-12 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:items-center lg:gap-16">
            <Reveal className="min-w-0">
              <SectionHead
                index="§2"
                legend="Composition"
                title="Collisions are found before code exists"
                tone="amber"
                lede="Two devices reaching for the same pin, the same I2C address or the same DMA stream is the classic way an embedded build fails silently. EmbeddPilot resolves the whole system's resource claims first and reports every clash by name."
              />
              <ul className="mt-7 flex flex-col gap-3">
                {[
                  "Pin-mux overlap across alternate functions",
                  "I2C address collisions on a shared bus",
                  "DMA stream and IRQ line contention",
                ].map((t) => (
                  <li
                    key={t}
                    className="flex items-start gap-3 text-[14px] leading-relaxed text-ink-dim"
                  >
                    <span
                      className="mt-[7px] h-[5px] w-[5px] shrink-0 rounded-full bg-accent"
                      aria-hidden
                    />
                    {t}
                  </li>
                ))}
              </ul>
            </Reveal>
            <Reveal delay={0.08} className="min-w-0">
              <ConflictReadout />
            </Reveal>
          </div>
        </Container>
      </section>

      {/* ============================================================ output */}
      <section className="py-20 sm:py-24">
        <Container wide>
          <div className="grid gap-12 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)] lg:items-center lg:gap-16">
            <Reveal className="order-2 min-w-0 lg:order-1">
              <RepoReadout />
            </Reveal>
            <Reveal delay={0.08} className="order-1 min-w-0 lg:order-2">
              <SectionHead
                index="§3"
                legend="Deliverable"
                title="A repository, not a snippet"
                lede="You get the application, the generated driver, the build system and the linker script — the same tree the emulator built and booted. Clone it and run make."
              />
              <div className="mt-8">
                <TargetSheet />
              </div>
            </Reveal>
          </div>
        </Container>
      </section>

      {/* ============================================================ ledger */}
      <section className="py-20 sm:py-24">
        <Container wide>
          <Reveal>
            <SectionHead
              index="§4"
              legend="Capability ledger"
              title="What is real, and what is not"
              lede="Embedded work punishes overclaiming harder than most software. This is the whole list — both halves of it."
            />
          </Reveal>
          <Reveal delay={0.06} className="mt-8">
            <ClaimBanner />
          </Reveal>
          <Reveal delay={0.1} className="mt-6">
            <CapabilityLedger />
          </Reveal>
        </Container>
      </section>

      {/* =============================================================== cta */}
      <section className="pb-8 pt-6">
        <Container wide>
          <Rule />
          <Reveal>
            <div className="flex flex-col gap-8 py-16 md:flex-row md:items-end md:justify-between">
              <div className="min-w-0 max-w-[34rem]">
                <Legend tone="accent">Start</Legend>
                <h2 className="site-display mt-4 text-[clamp(1.9rem,5.6vw,3.1rem)] font-semibold text-white">
                  Describe a device. Watch it boot.
                </h2>
                <p className="site-lede mt-4 text-[15px] leading-relaxed text-ink-dim">
                  The free tier generates three applications a month, with
                  emulation verification and I2C included.
                </p>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row">
                <ActionLink href="/app" kind="primary" className="sm:!px-5">
                  Open the workspace
                </ActionLink>
                <ActionLink href="/pricing" kind="default">
                  See pricing
                </ActionLink>
              </div>
            </div>
          </Reveal>
        </Container>
      </section>
    </>
  );
}
