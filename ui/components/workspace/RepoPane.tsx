"use client";

/* The repo, beside the conversation. Before a build exists this says what WILL
   be produced rather than showing an empty void — but it never shows file
   contents that do not exist yet, because a preview indistinguishable from
   output is the same lie in a friendlier font. */

import { useState } from "react";

const PLANNED = [
  ["src/main.c", "the application: MCU bring-up, the device conversation, your trigger → action"],
  ["Makefile", "builds it with arm-none-eabi-gcc"],
  ["link/stm32f4.ld", "the linker script, so the repo builds standalone"],
  ["README.md", "what was verified — and what was not"],
] as const;

export function RepoPane({
  files,
  jobId,
  building,
}: {
  files?: Record<string, string>;
  jobId: string | null;
  building: boolean;
}) {
  const names = Object.keys(files ?? {}).sort();
  const [open, setOpen] = useState<string | null>(null);
  const shown = open && files?.[open] ? open : names[0];

  if (!names.length) {
    return (
      <div className="flex min-h-0 flex-1 flex-col p-4">
        <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint">
          {building ? "generating…" : "no repo yet"}
        </p>
        <p className="mt-2 text-[12px] leading-relaxed text-ink-dim">
          {building
            ? "The build is running. Files appear here when it returns."
            : "Once the requirement is clear, a complete buildable repo is generated here:"}
        </p>
        <ul className="mt-3 flex flex-col gap-2">
          {PLANNED.map(([f, why]) => (
            <li key={f} className="border-l border-line pl-3">
              <span className="font-mono text-[11.5px] text-ink-dim">{f}</span>
              <p className="font-mono text-[10px] leading-relaxed text-ink-faint">
                {why}
              </p>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line px-3 py-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint">
          {names.length} files
        </span>
        {jobId && (
          <a
            href={`/api/v2/jobs/${jobId}/repo.zip`}
            className="border border-accent-dim px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-accent transition-colors hover:bg-accent/10"
          >
            download .zip
          </a>
        )}
      </div>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <ul className="flex shrink-0 gap-1 overflow-x-auto border-b border-line p-2 md:w-52 md:flex-col md:overflow-y-auto md:border-b-0 md:border-r">
          {names.map((n) => (
            <li key={n}>
              <button
                type="button"
                onClick={() => setOpen(n)}
                className={`w-full whitespace-nowrap px-2 py-1 text-left font-mono text-[11px] transition-colors ${
                  n === shown
                    ? "bg-accent/10 text-accent"
                    : "text-ink-faint hover:text-ink"
                }`}
              >
                {n}
              </button>
            </li>
          ))}
        </ul>
        <pre className="min-h-0 flex-1 overflow-auto p-3 font-mono text-[11px] leading-relaxed text-ink-dim">
          {shown ? files?.[shown] : ""}
        </pre>
      </div>
    </div>
  );
}
