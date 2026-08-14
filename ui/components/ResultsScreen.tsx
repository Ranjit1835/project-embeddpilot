"use client";

/* Screen 4: code viewer + provenance. Unverified fields highlight their
   marked lines; the fallback case renders unmistakably as UNVALIDATED with
   the register map offered for manual work. */

import { motion } from "framer-motion";
import { useMemo, useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { downloadUrl } from "../lib/api";
import { downloadDemoBundle } from "../lib/demo";
import type { GenerationResult } from "../lib/types";
import { Button, EASE, Panel, VerdictBadge, type Verdict } from "./ui";

const codeTheme: Record<string, React.CSSProperties> = {
  'pre[class*="language-"]': { background: "transparent", margin: 0 },
  'code[class*="language-"]': { background: "transparent" },
  comment: { color: "#7a8899", fontStyle: "italic" },
  macro: { color: "#e0a63c" },
  keyword: { color: "#5cc9f5" },
  string: { color: "#3fe081" },
  number: { color: "#e0a63c" },
  function: { color: "#c9d4df" },
};

export function ResultsScreen({
  result,
  jobId,
  onStartOver,
}: {
  result: GenerationResult;
  jobId: string;
  onStartOver: () => void;
}) {
  const files = result.files ?? {};
  const fileNames = Object.keys(files);
  const [active, setActive] = useState(fileNames[0] ?? "");
  const [copied, setCopied] = useState(false);
  const lastReport = result.reports?.[result.reports.length - 1];
  const unverified = (result.unverified_fields ?? []).filter(Boolean);
  const cores = lastReport?.cores ?? [];
  const scope = lastReport?.scope ?? [];
  const isFallback = result.status === "unvalidated";
  // which compiler actually ran (Priority 3): the validator records it in notes
  const compiler = lastReport?.notes
    ?.find((n) => n.toLowerCase().startsWith("compiler:"))
    ?.split(":")
    .slice(1)
    .join(":")
    .trim();
  // provider.name is "<provider>/<model>" (e.g. "nvidia/openai/gpt-oss-120b");
  // surface both, same principle as requested-vs-actual compiler labeling.
  const providerName = result.provider?.split("/")[0];
  const modelName = result.provider?.split("/").slice(1).join("/");

  const unverifiedLines = useMemo(() => {
    const m = new Map<string, Set<number>>();
    for (const u of unverified) {
      if (!m.has(u.file)) m.set(u.file, new Set());
      // highlight the define line and its UNVERIFIED comment line above
      m.get(u.file)!.add(u.line);
      m.get(u.file)!.add(u.line - 1);
    }
    return m;
  }, [unverified]);

  const copy = async () => {
    await navigator.clipboard.writeText(files[active] ?? "");
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={EASE}
      className="grid gap-4 w-full"
    >
      <div className="flex items-center justify-between flex-wrap gap-3">
        <VerdictBadge verdict={result.status as Verdict} />
        <div className="flex gap-2">
          {jobId.startsWith("demo:") ? (
            <Button onClick={() => downloadDemoBundle(jobId.slice(5))}>
              Download bundle (.json)
            </Button>
          ) : (
            <a href={downloadUrl(jobId)} download>
              <Button>Download all (.zip)</Button>
            </a>
          )}
          <Button onClick={onStartOver}>New datasheet</Button>
        </div>
      </div>

      {isFallback && (
        <Panel title="Unvalidated output — proceed manually">
          <div className="p-3 grid gap-2 text-[13px]">
            <p className="text-red">{result.message}</p>
            <p className="text-ink-dim">
              The zip download includes the extracted register map
              (register-map.json) and the exact validation failures so you can
              continue by hand.
            </p>
            {(result.validation_failures?.length ?? 0) > 0 && (
              <pre className="overflow-x-auto bg-bg border border-line rounded-sm p-2.5 font-mono text-[12px] text-red/90 leading-relaxed">
                {result
                  .validation_failures!.map(
                    (f) =>
                      `[${f.check}] ${f.file}${f.line ? ":" + f.line : ""}\n${f.message}`,
                  )
                  .join("\n\n")}
              </pre>
            )}
          </div>
        </Panel>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_320px] items-start">
        {fileNames.length > 0 && (
          <Panel>
            <div role="tablist" className="flex border-b border-line">
              {fileNames.map((f) => (
                <button
                  key={f}
                  role="tab"
                  aria-selected={active === f}
                  onClick={() => setActive(f)}
                  className={`px-3 py-1.5 font-mono text-[12px] border-r border-line transition-colors ${
                    active === f
                      ? "text-accent bg-panel-2"
                      : "text-ink-dim hover:text-ink"
                  }`}
                >
                  {f}
                </button>
              ))}
              <div className="ml-auto px-2 py-1">
                <button
                  onClick={copy}
                  className="text-[12px] text-ink-dim hover:text-ink"
                >
                  {copied ? "copied ✓" : "copy"}
                </button>
              </div>
            </div>
            <div className="overflow-x-auto text-[12.5px] leading-relaxed p-2">
              <SyntaxHighlighter
                language="c"
                style={codeTheme}
                showLineNumbers
                wrapLines
                lineNumberStyle={{ color: "#4d5a68", minWidth: "3em" }}
                lineProps={(n: number) => ({
                  id: `L-${active}-${n}`,
                  style: unverifiedLines.get(active)?.has(n)
                    ? {
                        display: "block",
                        background: "rgba(224,166,60,0.12)",
                        borderLeft: "2px solid #e0a63c",
                      }
                    : { display: "block" },
                })}
              >
                {files[active] ?? ""}
              </SyntaxHighlighter>
            </div>
          </Panel>
        )}

        <div className="grid gap-4">
          <Panel title="Provenance">
            <dl className="p-3 grid gap-1.5 text-[12.5px]">
              <Row k="Route" v={result.decision?.user_label ?? "—"} />
              <Row k="Reason" v={result.decision?.reason ?? "—"} dim />
              {result.target && (
                <Row
                  k="Output"
                  v={result.target === "arduino" ? "Arduino library" : "Bare-metal C driver"}
                  mono
                  tone="accent"
                />
              )}
              <Row k="Provider" v={providerName ?? "—"} mono tone="accent" />
              <Row k="Model" v={modelName ?? "—"} mono />
              {compiler && <Row k="Compiler" v={compiler} mono tone="accent" />}
              <Row k="Attempts" v={String(result.attempts ?? "—")} mono />
              {result.register_map && (
                <Row
                  k="Source pages"
                  v={result.register_map.source_pages?.join(", ") ?? "—"}
                  mono
                />
              )}
              {lastReport &&
                Object.entries(lastReport.checks).map(([check, state]) => (
                  <Row
                    key={check}
                    k={check.replace(/_/g, " ")}
                    v={state === "pass" ? "✓ pass" : state === "fail" ? "✕ fail" : "– skipped"}
                    mono
                    tone={state === "pass" ? "accent" : state === "fail" ? "red" : "dim"}
                  />
                ))}
              {(result.user_edits?.length ?? 0) > 0 && (
                <Row k="User edits" v={`${result.user_edits!.length} (in zip)`} mono />
              )}
            </dl>
          </Panel>

          {cores.length > 0 && (
            <Panel title="Compiled cores">
              <ul className="p-3 grid gap-1.5 text-[12.5px]">
                {cores.map((c, i) => {
                  const tone =
                    c.result === "pass"
                      ? "text-accent"
                      : c.result === "fail"
                        ? "text-red"
                        : "text-ink-faint";
                  const mark = c.result === "pass" ? "✓" : c.result === "fail" ? "✕" : "–";
                  return (
                    <li key={i} className="grid gap-0.5">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="text-ink">{c.name}</span>
                        <span className={`font-mono ${tone}`}>
                          {mark} {c.result}
                        </span>
                      </div>
                      {c.fqbn && (
                        <span className="font-mono text-[10.5px] text-ink-faint">{c.fqbn}</span>
                      )}
                      {c.detail && c.result !== "pass" && (
                        <pre className="overflow-x-auto bg-bg border border-line rounded-sm p-2 font-mono text-[11px] text-red/90 leading-relaxed whitespace-pre-wrap">
                          {c.detail}
                        </pre>
                      )}
                    </li>
                  );
                })}
              </ul>
            </Panel>
          )}

          {scope.length > 0 && (
            <Panel title="What was verified — 7 items">
              <ul className="p-3 grid gap-2 text-[12px]">
                {scope.map((s) => (
                  <li key={s.item} className="grid gap-0.5">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-ink">
                        <span className="text-ink-faint">{s.item}.</span> {s.title}
                      </span>
                      <ScopeBadge status={s.status} />
                    </div>
                    <span className="text-[11px] text-ink-faint leading-snug">{s.detail}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          {unverified.length > 0 && (
            <Panel title={`Unverified fields (${unverified.length})`}>
              <ul className="p-3 grid gap-1.5">
                {unverified.map((u, i) => (
                  <li key={i} className="text-[12px] font-mono">
                    <button
                      className="text-amber hover:underline underline-offset-2 text-left"
                      onClick={() => {
                        setActive(u.file);
                        requestAnimationFrame(() =>
                          document
                            .getElementById(`L-${u.file}-${u.line}`)
                            ?.scrollIntoView({ behavior: "smooth", block: "center" }),
                        );
                      }}
                    >
                      {u.define} {u.claimed_bits}
                    </button>
                    <span className="text-ink-faint">
                      {" "}
                      · {u.file}:{u.line} · reg {u.register}
                      {u.source_pages.length > 0 && ` · p.${u.source_pages.join(",")}`}
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          {(result.user_edits?.length ?? 0) > 0 && (
            <Panel title="Review-screen edits">
              <ul className="p-3 grid gap-0.5 font-mono text-[11.5px] text-ink-dim">
                {result.user_edits!.map((e, i) => (
                  <li key={i}>· {e}</li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function ScopeBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    "cross-checked": { label: "cross-checked", cls: "text-accent border-accent-dim bg-accent/10" },
    "marked-unverified": { label: "unverified", cls: "text-amber border-amber/40 bg-amber/10" },
    "platform-owned": { label: "platform", cls: "text-ink-dim border-line-2 bg-panel-2" },
    "your-input": { label: "your input", cls: "text-ink border-line-2 bg-panel-2" },
    "not-covered": { label: "not covered", cls: "text-ink-faint border-line-2" },
  };
  const s = map[status] ?? { label: status, cls: "text-ink-faint border-line-2" };
  return (
    <span
      className={`shrink-0 border rounded-sm px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide ${s.cls}`}
    >
      {s.label}
    </span>
  );
}

function Row({
  k,
  v,
  mono,
  dim,
  tone,
}: {
  k: string;
  v: string;
  mono?: boolean;
  dim?: boolean;
  tone?: "accent" | "red" | "dim";
}) {
  const toneCls =
    tone === "accent"
      ? "text-accent"
      : tone === "red"
        ? "text-red"
        : tone === "dim"
          ? "text-ink-faint"
          : dim
            ? "text-ink-dim"
            : "text-ink";
  return (
    <div className="grid grid-cols-[110px_1fr] gap-2 items-baseline">
      <dt className="text-[10px] uppercase tracking-[0.1em] text-ink-faint">{k}</dt>
      <dd className={`${mono ? "font-mono" : ""} ${toneCls} break-words`}>{v}</dd>
    </div>
  );
}
