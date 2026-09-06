"use client";

/* Settings.
 *
 * Two halves, and the split is the point. THIS DEPLOYMENT reports what the
 * backend can actually do right now — read-only, fetched, never assumed. YOUR
 * PREFERENCES are local to this browser.
 *
 * There is no API-key field, here or anywhere. On a shared deployment a key box
 * is either an invitation to hand your credential to a server you do not
 * control, or one key quietly shared between strangers. Keys belong in the
 * backend environment; this page only reports what that environment yielded.
 *
 * The capability panel exists so a missing tool is legible BEFORE a run rather
 * than as a mystery afterwards: "emulation skipped" means something very
 * different when you can see that this box has no Renode. */

import { useEffect, useState } from "react";
import { Bay, Led, Rule, Screws } from "../../../../components/resource-map/chrome";
import {
  DEFAULT_PREFS,
  fetchCapabilities,
  loadPrefs,
  savePrefs,
  type Capabilities,
  type OutputTarget,
  type Prefs,
} from "../../../../lib/prefs";

const TARGETS: { value: OutputTarget; label: string; note: string }[] = [
  { value: "cmake-project", label: "CMake project", note: "portable, make/ninja" },
  { value: "platformio-project", label: "PlatformIO", note: "board configs included" },
  { value: "arduino-sketch", label: "Arduino sketch", note: "V1 driver path" },
];

const PLATFORMS = ["stm32", "esp32", "avr", "nxp", "ti", "raspberry-pi", "other"];

export default function SettingsPage() {
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [capErr, setCapErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => setPrefs(loadPrefs()), []);
  useEffect(() => {
    fetchCapabilities().then(setCaps).catch((e) => setCapErr(String(e)));
  }, []);

  function update<K extends keyof Prefs>(k: K, v: Prefs[K]) {
    const next = { ...prefs, [k]: v };
    setPrefs(next);
    savePrefs(next);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1400);
  }

  return (
    <div className="ins-room flex min-h-screen flex-col">
      <header className="ins-chassis relative flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-2.5">
        <Screws />
        <div className="flex items-baseline gap-3">
          <a href="/app" className="text-[13px] font-bold uppercase tracking-[0.3em] text-ink">
            Embedd<span className="text-accent">Pilot</span>
          </a>
          <span className="ins-mono text-[10px] uppercase tracking-[0.18em] text-ink-faint">
            settings
          </span>
        </div>
        <a
          href="/app"
          className="ins-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint underline decoration-line underline-offset-4 transition-colors hover:text-accent"
        >
          ← back to the workspace
        </a>
      </header>

      <main className="mx-auto grid w-full max-w-5xl flex-1 gap-3 p-3 lg:grid-cols-2">
        {/* ---------------------------------------------- this deployment */}
        <Bay legend="this deployment" tone="dim" className="min-h-0">
          <div className="flex flex-col gap-3 p-3">
            <p className="ins-mono text-[10px] leading-relaxed text-ink-faint">
              Reported by the backend, not assumed by this page. A tool that is
              missing here is why a check will say “skipped” later.
            </p>

            {capErr && (
              /* A 404 here is not a broken backend — it is a backend older than
                 this endpoint. Saying so is more useful than a raw error, and
                 still does not pretend to know what that deployment can do. */
              <div className="ins-hazard-edge border border-amber/40 p-2.5">
                <p className="ins-mono text-[11px] text-amber">
                  {/404/.test(capErr)
                    ? "this backend predates the capabilities endpoint"
                    : "could not read capabilities"}
                </p>
                <p className="ins-mono mt-1 text-[10px] leading-relaxed text-ink-faint">
                  {/404/.test(capErr)
                    ? "Redeploy the API to see what this deployment can do. Nothing is shown in its place — an assumed toolchain would be a guess, and a guess about whether emulation can run is exactly the kind this product refuses to make."
                    : capErr}
                </p>
              </div>
            )}

            {caps && (
              <>
                <div>
                  <div className="ins-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint">
                    language model
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <Led tone={caps.provider.available ? "green" : "red"} />
                    <span className="ins-mono text-[12px] text-ink">
                      {caps.provider.name ?? "unavailable"}
                    </span>
                  </div>
                  {!caps.provider.available && caps.provider.reason && (
                    <p className="ins-mono mt-1 text-[10px] text-red">
                      {caps.provider.reason}
                    </p>
                  )}
                  <p className="ins-mono mt-1 text-[10px] text-ink-faint">
                    Configured in the backend environment. There is no key field
                    in this UI — see “running your own” below.
                  </p>
                </div>

                <Rule />

                <div>
                  <div className="ins-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint">
                    toolchain
                  </div>
                  <ul className="mt-1 flex flex-col gap-1.5">
                    {Object.entries(caps.toolchain).map(([name, t]) => (
                      <li key={name} className="flex items-start gap-2">
                        <span className="mt-[3px]">
                          <Led tone={t.available ? "green" : "amber"} />
                        </span>
                        <div className="min-w-0">
                          <span className="ins-mono text-[11px] text-ink">
                            {name.replace(/_/g, "-")}
                          </span>
                          {!t.available && (
                            <p className="ins-mono text-[10px] leading-relaxed text-amber">
                              {caps.consequences[name]}
                            </p>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>

                <Rule />

                <div className="flex flex-wrap gap-x-6 gap-y-2">
                  <div>
                    <div className="ins-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint">
                      buses
                    </div>
                    <div className="ins-mono text-[12px] text-accent">
                      {caps.buses_supported.join(" · ")}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <div className="ins-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint">
                      not built yet
                    </div>
                    <div className="ins-mono text-[11px] text-ink-dim">
                      {caps.not_built.join(" · ")}
                    </div>
                  </div>
                </div>
              </>
            )}

            {!caps && !capErr && (
              <p className="ins-mono text-[11px] text-ink-faint">reading…</p>
            )}
          </div>
        </Bay>

        {/* ------------------------------------------------ your preferences */}
        <div className="flex min-h-0 flex-col gap-3">
          <Bay
            legend="your preferences"
            right={
              saved ? (
                <span className="ins-mono text-[10px] uppercase tracking-[0.16em] text-accent">
                  saved
                </span>
              ) : null
            }
          >
            <div className="flex flex-col gap-4 p-3">
              <p className="ins-mono text-[10px] text-ink-faint">
                Stored in this browser only. Nothing here is sent anywhere.
              </p>

              <fieldset>
                <legend className="ins-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint">
                  default output target
                </legend>
                <div className="mt-2 flex flex-col gap-1.5">
                  {TARGETS.map((t) => (
                    <label key={t.value} className="flex cursor-pointer items-start gap-2">
                      <input
                        type="radio"
                        name="target"
                        checked={prefs.outputTarget === t.value}
                        onChange={() => update("outputTarget", t.value)}
                        className="mt-[3px] accent-[#3fe081]"
                      />
                      <span className="min-w-0">
                        <span className="ins-mono text-[11.5px] text-ink">{t.label}</span>
                        <span className="ins-mono ml-2 text-[10px] text-ink-faint">
                          {t.note}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <fieldset>
                <legend className="ins-mono text-[10px] uppercase tracking-[0.16em] text-ink-faint">
                  default platform
                </legend>
                <select
                  value={prefs.platform}
                  onChange={(e) => update("platform", e.target.value)}
                  className="ins-key mt-2 w-full border border-line bg-panel px-2 py-1.5 ins-mono text-[11.5px] text-ink"
                >
                  {PLATFORMS.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
                <p className="ins-mono mt-1 text-[10px] text-ink-faint">
                  A default only. The spec still asks, and your answer wins —
                  this never silently fills the field.
                </p>
              </fieldset>

              <Rule />

              <label className="flex cursor-pointer items-start gap-2">
                <input
                  type="checkbox"
                  checked={prefs.reduceMotion}
                  onChange={(e) => update("reduceMotion", e.target.checked)}
                  className="mt-[3px] accent-[#3fe081]"
                />
                <span>
                  <span className="ins-mono text-[11.5px] text-ink">reduce motion</span>
                  <p className="ins-mono text-[10px] text-ink-faint">
                    fewer animations on the board and console
                  </p>
                </span>
              </label>

              <label className="flex cursor-pointer items-start gap-2">
                <input
                  type="checkbox"
                  checked={prefs.showRawNotes}
                  onChange={(e) => update("showRawNotes", e.target.checked)}
                  className="mt-[3px] accent-[#3fe081]"
                />
                <span>
                  <span className="ins-mono text-[11.5px] text-ink">
                    show raw validator notes
                  </span>
                  <p className="ins-mono text-[10px] text-ink-faint">
                    the full note text from every check, not the summary
                  </p>
                </span>
              </label>
            </div>
          </Bay>

          <Bay legend="running your own" tone="dim">
            <div className="flex flex-col gap-2 p-3">
              <p className="ins-mono text-[10px] leading-relaxed text-ink-faint">
                Keys are read from the environment and never from this UI. To run
                EmbeddPilot with your own model provider, clone the repo and set:
              </p>
              <pre className="ins-face overflow-x-auto p-2 ins-mono text-[10.5px] text-ink-dim">
{`EMBEDDPILOT_PROVIDER=gemini   # or nvidia | groq
GEMINI_API_KEY=...            # never committed`}
              </pre>
              <a
                href="https://github.com/Ranjit1835/project-embeddpilot"
                target="_blank"
                rel="noreferrer"
                className="ins-mono text-[10.5px] text-accent underline decoration-accent-dim underline-offset-4"
              >
                github.com/Ranjit1835/project-embeddpilot →
              </a>
            </div>
          </Bay>
        </div>
      </main>
    </div>
  );
}
