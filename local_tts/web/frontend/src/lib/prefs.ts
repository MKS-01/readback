// User preferences persisted to localStorage. Bumped to v9 from v8 to add
// `persona`, `inputMode`, `toolsEnabled`. The migration copies forward every
// known v8 key before the first setter writes.

export interface Prefs {
  orbSize: number;
  showMeter: boolean;
  showCaptions: boolean;
  theme: string;
  micId: string | null;
  sttModel: string | null;
  voice: string | null;
  speed: number;
  // Phase 4/5 additions — defaults are no-op so behavior is unchanged.
  persona: string | null;
  customPersonaPrompt: string | null;
  inputMode: "vad" | "wake_word";
  toolsEnabled: boolean;
}

export const PREFS_KEY = "local-tts.prefs.v9";
const LEGACY_KEY = "local-tts.prefs.v8";

export const defaultPrefs: Prefs = {
  orbSize: 240,
  showMeter: true,
  showCaptions: true,
  theme: "ghost",
  micId: null,
  sttModel: null,
  voice: null,
  speed: 1.0,
  persona: null,
  customPersonaPrompt: null,
  inputMode: "vad",
  toolsEnabled: false,
};

export function loadPrefs(): Prefs {
  try {
    // One-shot migration: read v8 prefs into v9 shape.
    const v9raw = localStorage.getItem(PREFS_KEY);
    if (v9raw) return { ...defaultPrefs, ...JSON.parse(v9raw) };
    const legacy = localStorage.getItem(LEGACY_KEY);
    if (legacy) {
      const migrated = { ...defaultPrefs, ...JSON.parse(legacy) };
      localStorage.setItem(PREFS_KEY, JSON.stringify(migrated));
      return migrated;
    }
    return { ...defaultPrefs };
  } catch {
    return { ...defaultPrefs };
  }
}

export function savePrefs(p: Prefs): void {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* quota or private-mode — silently ignore */
  }
}
