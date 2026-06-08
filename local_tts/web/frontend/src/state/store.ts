// Zustand store for the article reader. Lives outside React so the WS client and
// three.js orb can push updates without re-mounting.

import { create } from "zustand";
import { defaultPrefs, loadPrefs, Prefs, savePrefs } from "../lib/prefs";

// Phase drives the orb (brain.ts). We reuse its existing vocabulary: "thinking"
// while a read job runs, "speaking" while audio plays, "idle" otherwise.
export type Phase = "idle" | "listening" | "thinking" | "speaking";
export type SwapState = "" | "loading" | "ready" | "error";

export interface VoiceOption {
  id: string;
  label: string;
}

export interface ReadResult {
  title: string;
  audioUrl: string;
  durationSec: number;
  wordCount: number;
  mode: string;
  // Spoken text for the transcript panel (summary mode only; null otherwise).
  text?: string | null;
}

export interface AppState {
  connected: boolean;
  phase: Phase;
  statusText: string;
  progress: { done: number; total: number } | null;
  busy: boolean;
  error: string;
  result: ReadResult | null;

  // server config
  voicesAvailable: VoiceOption[];
  model: string;

  // prefs
  prefs: Prefs;

  setConnected: (connected: boolean) => void;
  setPhase: (phase: Phase, statusText?: string) => void;
  setStatus: (statusText: string) => void;
  setProgress: (p: { done: number; total: number } | null) => void;
  setBusy: (busy: boolean) => void;
  setError: (error: string) => void;
  setResult: (result: ReadResult | null) => void;
  setSession: (patch: Partial<AppState>) => void;
  patchPrefs: (patch: Partial<Prefs>) => void;
}

const initialPrefs = loadPrefs();

export const useAppStore = create<AppState>((set, get) => ({
  connected: false,
  phase: "idle",
  statusText: "",
  progress: null,
  busy: false,
  error: "",
  result: null,

  voicesAvailable: [],
  model: "",

  prefs: initialPrefs,

  setConnected: (connected) => set({ connected }),
  setPhase: (phase, statusText) =>
    set(statusText !== undefined ? { phase, statusText } : { phase }),
  setStatus: (statusText) => set({ statusText }),
  setProgress: (progress) => set({ progress }),
  setBusy: (busy) => set({ busy }),
  setError: (error) => set({ error }),
  setResult: (result) => set({ result }),
  setSession: (patch) => set(patch),
  patchPrefs: (patch) => {
    const next = { ...get().prefs, ...patch };
    set({ prefs: next });
    savePrefs(next);
  },
}));

export function patchPrefs(patch: Partial<Prefs>) {
  useAppStore.getState().patchPrefs(patch);
}

export { defaultPrefs };
export type { Prefs };
