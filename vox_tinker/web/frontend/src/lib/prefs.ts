// User preferences persisted to localStorage. Bumped to v10 from v9 to add
// `sttEngine` (Parakeet/Whisper). The migration copies forward every known
// older key before the first setter writes.

export interface Prefs {
  orbSize: number;
  showMeter: boolean;
  showCaptions: boolean;
  theme: string;
  micId: string | null;
  sttEngine: string | null;
  sttModel: string | null;
  voice: string | null;
  speed: number;
  // Phase 4/5 additions — defaults are no-op so behavior is unchanged.
  persona: string | null;
  customPersonaPrompt: string | null;
  inputMode: "vad" | "wake_word";
  toolsEnabled: boolean;
}

export const PREFS_KEY = "vox-tinker.prefs.v10";
const LEGACY_KEYS = ["vox-tinker.prefs.v9", "vox-tinker.prefs.v8"];

export const defaultPrefs: Prefs = {
  orbSize: 240,
  showMeter: true,
  showCaptions: true,
  theme: "ghost",
  micId: null,
  sttEngine: null,
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
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) return { ...defaultPrefs, ...JSON.parse(raw) };
    // One-shot migration: read the newest available legacy key forward.
    for (const key of LEGACY_KEYS) {
      const legacy = localStorage.getItem(key);
      if (legacy) {
        const migrated = { ...defaultPrefs, ...JSON.parse(legacy) };
        localStorage.setItem(PREFS_KEY, JSON.stringify(migrated));
        return migrated;
      }
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
