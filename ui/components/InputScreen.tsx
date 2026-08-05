"use client";

/* Screen 1: datasheet input + live ingestion stages.
   V1.6: file upload is the primary path; the URL is a demoted secondary option
   (engineers found uploads extract better). Chip / interface / platform are no
   longer typed here — they are detected from the document and confirmed on the
   review screen, so this screen asks for as little as possible. */

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { getSample, listSamples, startIngest, subscribeJob } from "../lib/api";
import { isDemoActive } from "../lib/demo";
import type { JobEvent, RegisterMap, Sample } from "../lib/types";
import { Button, CheckGlyph, EASE, Field, Panel, inputCls } from "./ui";

const STAGES: [string, string][] = [
  ["uploaded", "Uploading"],
  ["extracting_text", "Extracting text"],
  ["extracting_tables", "Extracting tables"],
  ["building_map", "Building register map"],
];

export function InputScreen({
  onMapReady,
}: {
  onMapReady: (map: RegisterMap, platform: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [useUrl, setUseUrl] = useState(false);
  const [pages, setPages] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [running, setRunning] = useState(false);
  const [stageIdx, setStageIdx] = useState(-1);
  const [error, setError] = useState("");
  const unsub = useRef<() => void>(null);

  useEffect(() => {
    listSamples().then(setSamples).catch(() => {});
    return () => unsub.current?.();
  }, []);

  const submit = useCallback(async () => {
    setError("");
    if (isDemoActive()) {
      setError(
        "Datasheet extraction needs the local backend — this hosted demo replays recorded runs; pick a sample map below.",
      );
      return;
    }
    if (!file && !url) {
      setError("Upload a datasheet file (or provide a URL below).");
      return;
    }
    if (file && file.size > 50 * 1024 * 1024) {
      setError("File exceeds the 50MB limit.");
      return;
    }
    const form = new FormData();
    if (file) form.append("file", file);
    else if (url) form.append("url", url);
    form.append("pages", pages);
    setRunning(true);
    setStageIdx(0);
    try {
      const jobId = await startIngest(form);
      unsub.current = subscribeJob(jobId, (e: JobEvent) => {
        if (e.type === "stage") {
          const i = STAGES.findIndex(([s]) => s === e.stage);
          if (i >= 0) setStageIdx(i);
        } else if (e.type === "job_done") {
          if (e.status === "error") {
            setError(e.error ?? "ingestion failed");
            setRunning(false);
          } else {
            setStageIdx(STAGES.length);
            fetch(`/api/jobs/${jobId}`)
              .then((r) => r.json())
              // platform is chosen on the review screen (not detectable)
              .then((snap) => onMapReady(snap.result.register_map, ""));
          }
        }
      });
    } catch (e) {
      setError(String(e));
      setRunning(false);
    }
  }, [file, url, pages, onMapReady]);

  const loadSample = async (id: string) => {
    setError("");
    try {
      const s = await getSample(id);
      onMapReady(s.register_map, s.platform);
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="grid gap-4 max-w-3xl mx-auto w-full">
      <Panel title="Datasheet input">
        <div className="p-4 grid gap-4">
          <div
            role="button"
            tabIndex={0}
            aria-label="Drop a PDF or DOCX datasheet, or press Enter to browse"
            onKeyDown={(e) => {
              if (e.key === "Enter")
                (document.getElementById("filepick") as HTMLInputElement)?.click();
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const f = e.dataTransfer.files?.[0];
              if (f) setFile(f);
            }}
            onClick={() =>
              (document.getElementById("filepick") as HTMLInputElement)?.click()
            }
            className={`border border-dashed rounded-sm px-4 py-8 text-center cursor-pointer transition-colors ${
              dragOver
                ? "border-accent bg-accent/5"
                : "border-line-2 hover:border-ink-faint"
            }`}
          >
            {file ? (
              <span className="font-mono text-[13px] text-accent">
                {file.name}{" "}
                <span className="text-ink-dim">
                  ({(file.size / 1024 / 1024).toFixed(1)} MB)
                </span>
              </span>
            ) : (
              <span className="text-ink-dim text-[13px]">
                Drop a PDF / DOCX datasheet here or click to browse
                <span className="block text-[11px] text-accent/80 mt-1">
                  recommended — uploading the file extracts more reliably than a link
                </span>
                <span className="block text-[11px] text-ink-faint mt-0.5">
                  max 50MB · vendor datasheets over 1,000 pages supported
                </span>
              </span>
            )}
            <input
              id="filepick"
              type="file"
              accept=".pdf,.docx"
              className="sr-only"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>

          <Field label="Page range (optional)">
            <input
              className={`${inputCls} sm:max-w-40`}
              placeholder="401-429"
              value={pages}
              onChange={(e) => setPages(e.target.value)}
            />
          </Field>

          {/* URL: demoted secondary option (Priority 4) */}
          <div className="border-t border-line pt-3">
            {!useUrl ? (
              <button
                onClick={() => setUseUrl(true)}
                className="text-[12px] text-ink-faint hover:text-ink-dim underline underline-offset-2"
              >
                or extract from a datasheet URL instead
              </button>
            ) : (
              <Field label="Datasheet URL (secondary)">
                <input
                  className={inputCls}
                  placeholder="https://vendor.com/datasheet.pdf"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
                <span className="text-[11px] text-ink-faint mt-1">
                  Links can be broken or blocked and extract less reliably —
                  prefer uploading the file above. The URL is checked (reachable,
                  a PDF/DOCX, under 50MB) before extraction.
                </span>
              </Field>
            )}
          </div>

          <div className="flex items-center gap-3">
            <Button kind="primary" onClick={submit} disabled={running}>
              {running ? "Extracting…" : "Extract register map"}
            </Button>
            {error && (
              <span role="alert" className="text-red text-[13px]">
                {error}
              </span>
            )}
          </div>
        </div>
      </Panel>

      {/* fixed-height rows: stages animate state, never shift layout */}
      <AnimatePresence>
        {running && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={EASE}
          >
            <Panel title="Extraction pipeline">
              <ol className="p-3 grid gap-1">
                {STAGES.map(([key, label], i) => {
                  const state =
                    i < stageIdx ? "pass" : i === stageIdx ? "active" : "pending";
                  return (
                    <li
                      key={key}
                      className="flex items-center gap-2.5 h-7 px-2 font-mono text-[13px]"
                    >
                      {state === "active" ? (
                        <motion.span
                          className="inline-block w-4 text-center text-accent"
                          animate={{ opacity: [0.3, 1, 0.3] }}
                          transition={{ repeat: Infinity, duration: 1.2 }}
                        >
                          ▸
                        </motion.span>
                      ) : (
                        <CheckGlyph state={state === "pass" ? "pass" : "pending"} />
                      )}
                      <span
                        className={
                          state === "pending" ? "text-ink-faint" : "text-ink"
                        }
                      >
                        {label}
                      </span>
                    </li>
                  );
                })}
              </ol>
            </Panel>
          </motion.div>
        )}
      </AnimatePresence>

      {samples.length > 0 && !running && (
        <Panel title="Live-proven sample maps">
          <div className="p-3 flex flex-wrap gap-2">
            {samples.map((s) => (
              <Button key={s.id} onClick={() => loadSample(s.id)}>
                {s.label}
              </Button>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}
