import type { Metadata } from "next";
import {
  Bay,
  Container,
  Led,
  Legend,
  Rule,
  SectionHead,
} from "@/components/site/kit";
import { Reveal, RevealItem } from "@/components/site/Reveal";

const EMAIL = "ranjitperumala@gmail.com";
const ISSUES = "https://github.com/Ranjit1835/project-embeddpilot/issues";

export const metadata: Metadata = {
  title: "Contact",
  description:
    "Reach EmbeddPilot by email at ranjitperumala@gmail.com for business, pricing and enterprise enquiries, or open a GitHub issue for bugs and feature requests.",
};

const CHANNELS: {
  legend: string;
  title: string;
  body: string;
  href: string;
  value: string;
  external: boolean;
  tone: "accent" | "cyan";
  use: string[];
}[] = [
  {
    legend: "Business · direct",
    title: "Email",
    body: "Pricing, enterprise and self-hosted deployments, partnerships, or anything you would rather not put in a public tracker.",
    href: `mailto:${EMAIL}`,
    value: EMAIL,
    external: true,
    tone: "accent",
    use: [
      "Enterprise and on-premises enquiries",
      "Pricing questions and invoicing",
      "Anything commercial or confidential",
    ],
  },
  {
    legend: "Engineering · public",
    title: "GitHub issues",
    body: "Bugs, incorrect generation, a failed emulated run, or a capability you need. Public, tracked, and linked to the code.",
    href: ISSUES,
    value: "github.com/Ranjit1835/project-embeddpilot/issues",
    external: true,
    tone: "cyan",
    use: [
      "A generated driver that does not match the datasheet",
      "An emulated run that fails or hangs",
      "Missing bus, device or target support",
    ],
  },
];

const REPORT_FIELDS: { k: string; v: string }[] = [
  { k: "requirement", v: "the plain-English requirement you entered" },
  { k: "device", v: "part number and bus — e.g. BMP180, I2C, 0x77" },
  { k: "datasheet", v: "which datasheet revision you supplied" },
  { k: "stage", v: "where it went wrong: spec / extraction / compose / generate / verify" },
  { k: "transcript", v: "the emulated boot output, including the exit code" },
  { k: "expected", v: "what the run should have printed instead" },
];

export default function ContactPage() {
  return (
    <>
      {/* =============================================================== head */}
      <section className="relative overflow-hidden border-b border-line">
        <div
          aria-hidden
          className="site-pcb site-pcb-fade pointer-events-none absolute inset-x-0 -top-20 h-[28rem]"
        />
        <Container wide className="relative">
          <div className="py-16 sm:py-20">
            <Reveal>
              <SectionHead
                as="h1"
                legend="Contact"
                title="Two ports, and neither of them is a chatbot"
                lede="EmbeddPilot is a small project. Replies are written by a person and are best-effort — but a reproducible bug report is always read."
              />
            </Reveal>
          </div>
        </Container>
      </section>

      {/* =========================================================== channels */}
      <section className="py-14 sm:py-16">
        <Container wide>
          <div className="grid gap-5 lg:grid-cols-2 lg:items-start">
            {CHANNELS.map((c, i) => (
              <RevealItem key={c.title} index={i} className="min-w-0">
                <article className="site-panel flex h-full flex-col rounded-sm">
                  <header className="flex items-center gap-2.5 border-b border-line px-5 py-3">
                    <Led
                      tone={c.tone === "accent" ? "green" : "cyan"}
                      breathe
                    />
                    <Legend tone={c.tone === "accent" ? "accent" : "dim"}>
                      {c.legend}
                    </Legend>
                  </header>

                  <div className="flex flex-1 flex-col px-5 py-6">
                    <h2 className="site-display text-[clamp(1.5rem,4.5vw,2rem)] font-semibold text-white">
                      {c.title}
                    </h2>
                    <p className="site-lede mt-3 text-[14px] leading-relaxed text-ink-dim">
                      {c.body}
                    </p>

                    <a
                      href={c.href}
                      target={c.href.startsWith("mailto:") ? undefined : "_blank"}
                      rel="noreferrer noopener"
                      className="site-mono site-break mt-6 inline-flex items-start gap-2 rounded-sm border border-line-2 bg-panel-2 px-3.5 py-3 text-[13px] text-accent transition-colors hover:border-accent-dim hover:bg-accent/[0.06]"
                    >
                      <span aria-hidden className="shrink-0 text-ink-faint">
                        ↳
                      </span>
                      {c.value}
                    </a>

                    <div className="mt-7">
                      <Legend>Use this for</Legend>
                      <ul className="mt-3.5 flex flex-col gap-2.5">
                        {c.use.map((u) => (
                          <li
                            key={u}
                            className="flex items-start gap-2.5 text-[13.5px] leading-relaxed text-ink-dim"
                          >
                            <span
                              aria-hidden
                              className="mt-[8px] h-[4px] w-[4px] shrink-0 rounded-full bg-ink-faint"
                            />
                            {u}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </article>
              </RevealItem>
            ))}
          </div>
        </Container>
      </section>

      {/* ========================================================== template */}
      <section className="py-14 sm:py-16">
        <Container wide>
          <div className="grid gap-12 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:gap-16">
            <Reveal className="min-w-0">
              <SectionHead
                legend="Bug reports"
                title="What to include"
                lede="Generation is deterministic — the same spec produces the same repository. That means a good report is almost always reproducible, and a reproducible report gets fixed."
              />
            </Reveal>

            <Reveal delay={0.06} className="min-w-0">
              <Bay legend="Report template" tone="accent" glass>
                {/* stacked at phone width, column-aligned once there is room */}
                <div className="px-4 py-5 sm:px-5">
                  <dl className="flex flex-col gap-4">
                    {REPORT_FIELDS.map((f) => (
                      <div
                        key={f.k}
                        className="sm:grid sm:grid-cols-[7.5rem_minmax(0,1fr)] sm:gap-x-4"
                      >
                        <dt className="site-mono text-[12px] text-accent">
                          {f.k}
                        </dt>
                        <dd className="site-mono mt-1 text-[12px] leading-relaxed text-ink-dim sm:mt-0">
                          {f.v}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </Bay>
              <p className="site-lede mt-5 text-[13.5px] leading-relaxed text-ink-dim">
                If the datasheet you used is not public, say so rather than
                attaching it — we will work out how to reproduce it another way.
              </p>
            </Reveal>
          </div>
        </Container>
      </section>

      {/* ============================================================== close */}
      <section className="pb-6">
        <Container wide>
          <Rule />
          <div className="grid gap-8 py-14 md:grid-cols-3">
            {[
              {
                h: "Enterprise",
                p: "Self-hosted and on-premises deployments are handled by email. Hardware-in-the-loop is on the roadmap and is not available today.",
              },
              {
                h: "Response time",
                p: "Best-effort. There is no support SLA outside an Enterprise agreement, and none is implied.",
              },
              {
                h: "Security",
                p: "If you have found something sensitive, email rather than filing a public issue.",
              },
            ].map((b) => (
              <div key={b.h} className="min-w-0">
                <Legend>{b.h}</Legend>
                <p className="site-lede mt-3 text-[13.5px] leading-relaxed text-ink-dim">
                  {b.p}
                </p>
              </div>
            ))}
          </div>
        </Container>
      </section>
    </>
  );
}
