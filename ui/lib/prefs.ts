/* Local preferences.
 *
 * These live in the browser, not on a server, because none of them are secrets
 * and none of them belong to anyone but you. There is deliberately no API-key
 * field here or anywhere else in the UI: on a shared deployment a key box is
 * either an invitation to hand your credential to someone else's server, or one
 * key quietly shared between strangers. Keys stay in the backend environment. */

export type OutputTarget = "cmake-project" | "platformio-project" | "arduino-sketch";

export interface Prefs {
  outputTarget: OutputTarget;
  platform: string;
  reduceMotion: boolean;
  showRawNotes: boolean;
}

export const DEFAULT_PREFS: Prefs = {
  outputTarget: "cmake-project",
  platform: "stm32",
  reduceMotion: false,
  showRawNotes: false,
};

const KEY = "embeddpilot.prefs.v1";

export function loadPrefs(): Prefs {
  if (typeof window === "undefined") return DEFAULT_PREFS;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return DEFAULT_PREFS;
    // merge rather than replace, so a pref added in a later version does not
    // arrive as undefined for anyone who saved settings before it existed
    return { ...DEFAULT_PREFS, ...(JSON.parse(raw) as Partial<Prefs>) };
  } catch {
    return DEFAULT_PREFS;
  }
}

export function savePrefs(p: Prefs): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    /* private mode / quota — preferences are a convenience, never load-bearing */
  }
}

export interface Capabilities {
  provider: { name: string | null; context_window: number | null;
              available: boolean; reason?: string };
  toolchain: Record<string, { available: boolean; path?: string | null }>;
  consequences: Record<string, string>;
  buses_supported: string[];
  not_built: string[];
}

export async function fetchCapabilities(): Promise<Capabilities> {
  const res = await fetch("/api/v2/capabilities");
  if (!res.ok) throw new Error(`capabilities: HTTP ${res.status}`);
  return res.json();
}
