/* Instrument panels used across the platform pages. All server components:
   the movement here is CSS, the structure is a spec sheet. */

import { Bay, Glyph, Led, Legend, ScrollX, Tag } from "./kit";

/* ------------------------------------------------------------- pipeline */

export const STAGES: {
  n: string;
  legend: string;
  title: string;
  body: string;
  out: string;
}[] = [
  {
    n: "01",
    legend: "Intake",
    title: "You describe the device in plain English",
    body: "EmbeddPilot asks clarifying questions until the requirement is unambiguous. It will not fill in a value it cannot ground in something you actually said.",
    out: "clarifying questions",
  },
  {
    n: "02",
    legend: "Spec",
    title: "Your answers become a structured specification",
    body: "Every field traces back to a statement you made. Anything still unknown is surfaced as unknown rather than guessed at.",
    out: "structured spec",
  },
  {
    n: "03",
    legend: "Extraction",
    title: "The datasheet becomes a cross-checked register map",
    body: "Addresses, fields and commands are pulled from the PDF and cross-checked. Ambiguous fields are flagged low-confidence instead of being invented.",
    out: "verified register map",
  },
  {
    n: "04",
    legend: "Compose",
    title: "Devices are placed on the MCU and checked for collisions",
    body: "Pin-mux overlaps, I2C address collisions and DMA/IRQ contention are detected across every device in the system — before a line of code exists.",
    out: "resource map",
  },
  {
    n: "05",
    legend: "Generate",
    title: "A complete, buildable repository is written",
    body: "src/main.c, the drivers, a Makefile, a linker script and a README. The application calls the verified driver from stage 03 — it does not re-derive it.",
    out: "buildable repo",
  },
  {
    n: "06",
    legend: "Verify",
    title: "The firmware is cross-compiled and made to run",
    body: "arm-none-eabi builds the ELF; Renode boots it on an emulated STM32F4 against mocked devices; a harness asserts the real UART output. The run either passes or it does not.",
    out: "emulated boot · exit 0",
  },
];

export function PipelineLedger() {
  return (
    <ol className="relative mt-12">
      {/* copper spine */}
      <span
        aria-hidden
        className="pointer-events-none absolute bottom-6 left-0 top-6 w-px bg-gradient-to-b from-transparent via-accent-dim/60 to-transparent"
      />
      {STAGES.map((s) => (
        <li
          key={s.n}
          className="relative border-b border-line/70 py-7 pl-6 last:border-b-0 sm:pl-8"
        >
          {/* node on the spine */}
          <span
            aria-hidden
            className="absolute left-0 top-[34px] flex h-[9px] w-[9px] -translate-x-1/2 items-center justify-center rounded-full border border-accent-dim bg-bg"
          >
            <span className="h-[3px] w-[3px] rounded-full bg-accent" />
          </span>

          <div className="grid gap-x-8 gap-y-3 md:grid-cols-[7rem_minmax(0,1fr)_11rem]">
            <div className="flex items-baseline gap-3 md:flex-col md:gap-2">
              <span className="site-mono text-[22px] leading-none text-ink-faint">
                {s.n}
              </span>
              <Legend>{s.legend}</Legend>
            </div>

            <div className="min-w-0">
              <h3 className="text-[17px] font-semibold leading-snug tracking-[-0.01em] text-white sm:text-[19px]">
                {s.title}
              </h3>
              <p className="site-lede mt-2.5 text-[14px] leading-relaxed text-ink-dim">
                {s.body}
              </p>
            </div>

            <div className="md:pt-1">
              <div className="flex flex-col gap-2">
                <Legend>Output</Legend>
                <span className="site-mono site-break text-[12px] text-accent">
                  {s.out}
                </span>
              </div>
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

/* ------------------------------------------------------------- conflicts */

const CONFLICTS: {
  resource: string;
  claim: string;
  by: string;
  state: "ok" | "clash";
  note?: string;
}[] = [
  { resource: "PA6", claim: "SPI1_MISO", by: "max31855", state: "ok" },
  {
    resource: "PA6",
    claim: "TIM3_CH1",
    by: "fan_pwm",
    state: "clash",
    note: "pin-mux overlap",
  },
  { resource: "I2C1 · 0x77", claim: "address", by: "bmp180", state: "ok" },
  {
    resource: "I2C1 · 0x77",
    claim: "address",
    by: "bme280",
    state: "clash",
    note: "bus address collision",
  },
  { resource: "DMA1 · stream 0", claim: "channel 1", by: "i2c1_rx", state: "ok" },
];

export function ConflictReadout() {
  const clashes = CONFLICTS.filter((c) => c.state === "clash").length;
  return (
    <Bay
      legend="Resource map · composed system"
      tone="amber"
      glass
      right={
        <span className="site-mono text-[10px] text-amber">
          {clashes} conflicts
        </span>
      }
    >
      {/* Phone: stacked cards, because the verdict is the point of the panel and
          must never be the column that gets clipped. Tablet up: the real table. */}
      <ul className="divide-y divide-line/60 sm:hidden">
        {CONFLICTS.map((c, i) => (
          <li key={`m-${c.resource}-${i}`} className="px-4 py-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="site-mono text-[12.5px] text-ink">
                {c.resource}
              </span>
              {c.state === "ok" ? (
                <span className="site-mono flex items-center gap-1.5 text-[11px] text-accent">
                  <Led tone="green" />
                  ok
                </span>
              ) : (
                <span className="site-mono flex items-center gap-1.5 text-right text-[11px] text-red">
                  <Led tone="red" blink />
                  {c.note}
                </span>
              )}
            </div>
            <p className="site-mono mt-1 text-[11.5px] text-ink-dim">
              {c.claim} · {c.by}
            </p>
          </li>
        ))}
      </ul>

      <ScrollX
        label="Resource conflict table"
        className="hidden sm:block"
      >
        <table className="w-full min-w-[28rem] border-collapse">
          <caption className="sr-only">
            Detected resource conflicts across the composed system
          </caption>
          <thead>
            <tr className="border-b border-line">
              {["Resource", "Claim", "Owner", "State"].map((h) => (
                <th
                  key={h}
                  scope="col"
                  className="site-legend px-4 py-2 text-left text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="site-mono text-[12px]">
            {CONFLICTS.map((c, i) => (
              <tr
                key={`${c.resource}-${i}`}
                className="border-b border-line/60 last:border-b-0"
              >
                <td className="px-4 py-2.5 text-ink">{c.resource}</td>
                <td className="px-4 py-2.5 text-ink-dim">{c.claim}</td>
                <td className="px-4 py-2.5 text-ink-dim">{c.by}</td>
                <td className="px-4 py-2.5">
                  {c.state === "ok" ? (
                    <span className="flex items-center gap-2 text-accent">
                      <Led tone="green" />
                      ok
                    </span>
                  ) : (
                    <span className="flex items-center gap-2 text-red">
                      <Led tone="red" blink />
                      {c.note}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollX>
    </Bay>
  );
}

/* ------------------------------------------------------------ repo tree */

const TREE: { d: number; name: string; kind: "dir" | "file"; note?: string }[] = [
  { d: 0, name: "project/", kind: "dir" },
  { d: 1, name: "src/", kind: "dir" },
  { d: 2, name: "main.c", kind: "file", note: "application" },
  { d: 1, name: "drivers/", kind: "dir" },
  { d: 2, name: "bmp180.c", kind: "file", note: "from the register map" },
  { d: 2, name: "bmp180.h", kind: "file" },
  { d: 1, name: "Makefile", kind: "file", note: "arm-none-eabi" },
  { d: 1, name: "stm32f405.ld", kind: "file", note: "linker script" },
  { d: 1, name: "README.md", kind: "file" },
];

export function RepoReadout() {
  return (
    <Bay legend="Generated repository" tone="accent" glass>
      <ScrollX
        label="Generated repository tree"
        className="px-4 py-4"
        fade="#0f161d"
      >
        <ul className="site-mono w-max text-[11px] leading-[1.9] sm:text-[12px]">
          {TREE.map((n, i) => (
            <li key={i} className="whitespace-pre">
              <span className="text-ink-faint">{"  ".repeat(n.d)}</span>
              <span className={n.kind === "dir" ? "text-ink" : "text-accent"}>
                {n.name}
              </span>
              {n.note && (
                <span className="text-ink-faint">{`  · ${n.note}`}</span>
              )}
            </li>
          ))}
        </ul>
      </ScrollX>
    </Bay>
  );
}

/* --------------------------------------------------------- target sheet */

const TARGETS: { label: string; value: string; state: "yes" | "no" | "partial" }[] =
  [
    { label: "Emulated MCU", value: "STM32F4 (Renode)", state: "yes" },
    { label: "Toolchain", value: "arm-none-eabi", state: "yes" },
    { label: "Buses", value: "I2C, SPI", state: "yes" },
    { label: "Multi-device systems", value: "supported", state: "yes" },
    { label: "UART peripheral devices", value: "roadmap", state: "no" },
    { label: "Physical flashing", value: "roadmap", state: "no" },
  ];

export function TargetSheet() {
  return (
    <Bay legend="Support matrix" tone="dim">
      <dl className="divide-y divide-line/60">
        {TARGETS.map((t) => (
          <div
            key={t.label}
            className="flex items-center justify-between gap-4 px-4 py-3"
          >
            <dt className="text-[13px] text-ink-dim">{t.label}</dt>
            <dd className="flex items-center gap-2.5 text-right">
              <span
                className={`site-mono text-[12px] ${
                  t.state === "yes" ? "text-ink" : "text-ink-faint"
                }`}
              >
                {t.value}
              </span>
              <Glyph state={t.state} />
            </dd>
          </div>
        ))}
      </dl>
    </Bay>
  );
}

/* ---------------------------------------------------------- proof strip */

export function ProofStrip() {
  const items = [
    { k: "Emulated target", v: "STM32F4" },
    { k: "Emulator", v: "Renode" },
    { k: "Buses", v: "I2C · SPI" },
    { k: "Invented values", v: "0" },
  ];
  return (
    <ul className="grid grid-cols-2 divide-line/70 border-y border-line md:grid-cols-4 md:divide-x">
      {items.map((it, i) => (
        <li
          key={it.k}
          className={`px-4 py-5 sm:px-6 ${
            i < 2 ? "border-b border-line/70 md:border-b-0" : ""
          } ${i % 2 === 1 ? "border-l border-line/70 md:border-l-0" : ""}`}
        >
          <Legend>{it.k}</Legend>
          <p className="site-mono mt-2.5 text-[16px] leading-none text-white sm:text-[19px]">
            {it.v}
          </p>
        </li>
      ))}
    </ul>
  );
}

/* --------------------------------------------------------- claim banner */

export function ClaimBanner() {
  return (
    <div className="relative overflow-hidden rounded-sm border border-amber/30 bg-amber/[0.05]">
      <span aria-hidden className="site-hazard absolute inset-y-0 left-0 w-1" />
      <div className="flex flex-col gap-2 py-4 pl-6 pr-4 sm:pl-7">
        <div className="flex items-center gap-2">
          <Led tone="amber" />
          <Legend tone="amber">The honest claim</Legend>
        </div>
        <p className="site-lede text-[14px] leading-relaxed text-ink sm:text-[15px]">
          EmbeddPilot proves behaviour{" "}
          <strong className="font-semibold text-amber">in emulation</strong>. A
          passing run is evidence the firmware builds, boots and produces the
          expected output against mocked devices. It is{" "}
          <strong className="font-semibold text-amber">not</strong> evidence
          that it works on physical silicon — timing, electrical behaviour and
          real part variance are not modelled.
        </p>
      </div>
    </div>
  );
}

export { Tag };
