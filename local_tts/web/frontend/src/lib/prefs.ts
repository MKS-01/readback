// User preferences persisted to localStorage. v12: project pivoted to the
// offline article reader — only voice + read-mode are remembered now.

export interface Prefs {
  theme: string;
  voice: string | null;
  mode: "full" | "summary";
}

export const PREFS_KEY = "local-tts.prefs.v12";

export const defaultPrefs: Prefs = {
  theme: "ghost",
  voice: null,
  mode: "full",
};

export function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) return { ...defaultPrefs, ...JSON.parse(raw) };
    return { ...defaultPrefs };
  } catch {
    return { ...defaultPrefs };
  }
}

export function savePrefs(p: Prefs): void {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* quota or private-mode — ignore */
  }
}
