/* The capability ledger. Two columns, no hedging: what has shipped and been
   exercised, and what has not been built. This exists so nobody has to guess
   which half of the marketing copy is true. */

import { Led, Legend } from "./kit";

export const SHIPPED: { title: string; note: string }[] = [
  {
    title: "Requirement → clarifying questions → structured spec",
    note: "The spec is built from your answers. No value is invented that cannot be grounded in something you said.",
  },
  {
    title: "Datasheet → cross-checked register map",
    note: "Register addresses, fields and commands are extracted from the PDF and cross-checked; ambiguity is flagged, not resolved by guessing.",
  },
  {
    title: "The generated application runs the verified driver",
    note: "The app calls the driver produced from that register map — it does not re-derive register access from memory.",
  },
  {
    title: "Resource conflict detection across composed devices",
    note: "Pin-mux overlaps, I2C address collisions and DMA/IRQ contention are found across every device in the system.",
  },
  {
    title: "A complete, buildable repository",
    note: "src/main.c, drivers, Makefile, linker script and README — a repo you can clone and build, not a snippet.",
  },
  {
    title: "Cross-compiled for ARM and booted on an emulated STM32F4",
    note: "Renode boots the firmware against mocked devices and a harness asserts the actual UART output. Pass or fail is a real result.",
  },
  {
    title: "I2C and SPI, including multi-device systems",
    note: "More than one peripheral on more than one bus, composed and checked together.",
  },
];

export const NOT_BUILT: { title: string; note: string }[] = [
  {
    title: "Flashing to physical hardware",
    note: "There is no flash path. EmbeddPilot never talks to a board.",
  },
  {
    title: "Hardware test or dump-success prediction",
    note: "Nothing here predicts how the firmware will behave on real silicon.",
  },
  {
    title: "UART peripheral devices",
    note: "UART is used as the emulator's output channel, not yet supported as a device bus.",
  },
  {
    title: "Richer application logic",
    note: "Timers, state machines and scheduled behaviour are not generated yet.",
  },
];

function Column({
  legend,
  tone,
  items,
  caption,
}: {
  legend: string;
  tone: "accent" | "amber";
  items: { title: string; note: string }[];
  caption: string;
}) {
  const accent = tone === "accent";
  return (
    <section
      className={`site-panel relative overflow-hidden rounded-sm ${
        accent ? "" : ""
      }`}
    >
      <span
        aria-hidden
        className={`absolute inset-y-0 left-0 w-1 ${
          accent ? "bg-accent-dim" : "site-hazard"
        }`}
      />
      <header className="flex items-center gap-2.5 border-b border-line py-3 pl-6 pr-4">
        <Led tone={accent ? "green" : "amber"} breathe={accent} />
        <Legend tone={tone}>{legend}</Legend>
      </header>
      <p className="border-b border-line/60 py-3 pl-6 pr-4 text-[13px] leading-relaxed text-ink-faint">
        {caption}
      </p>
      <ul className="divide-y divide-line/60">
        {items.map((it) => (
          <li key={it.title} className="py-4 pl-6 pr-4">
            <p
              className={`text-[14.5px] font-medium leading-snug ${
                accent ? "text-white" : "text-ink"
              }`}
            >
              {it.title}
            </p>
            <p className="site-lede mt-1.5 text-[13px] leading-relaxed text-ink-dim">
              {it.note}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function CapabilityLedger() {
  return (
    <div className="grid gap-5 lg:grid-cols-2 lg:items-start">
      <Column
        legend="Shipped · exercised"
        tone="accent"
        caption="Built, running, and demonstrated by an emulated run you can inspect."
        items={SHIPPED}
      />
      <Column
        legend="Not built yet · roadmap"
        tone="amber"
        caption="Listed here so it is never implied anywhere else on this site."
        items={NOT_BUILT}
      />
    </div>
  );
}
