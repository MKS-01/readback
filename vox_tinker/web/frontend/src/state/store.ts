// Zustand store. Single source of truth for everything React renders. The
// audio engine, WS client, and brain controller live OUTSIDE the store as
// singletons; they only push events into it via setters.

import { create } from "zustand";
import { defaultPrefs, loadPrefs, Prefs, savePrefs } from "../lib/prefs";

export type Phase = "idle" | "listening" | "thinking" | "speaking";
export type SwapState = "" | "loading" | "ready" | "error";

export interface VoiceOption {
  id: string;
  label: string;
}

export interface AppState {
  // --- session / config ---
  sessionId: string | null;
  voice: string | null;
  voicesAvailable: VoiceOption[];
  model: string | null;
  modelsAvailable: string[];
  sttEngine: string | null;
  sttEnginesAvailable: string[];
  sttModel: string | null;
  sttModelsAvailable: string[];
  turnEnabled: boolean; // Smart-Turn active server-side
  turnWaiting: boolean; // mid-thought pause: model said "not done yet"
  persona: string | null;
  personasAvailable: string[];
  personaStatus: { text: string; kind: SwapState };
  toolsEnabled: boolean;
  toolsAvailable: string[];
  toolsAllowed: string[];
  inputMode: "vad" | "wake_word";
  wakewordModel: string | null;
  wakewordDisplayName: string | null;
  inputModeStatus: { text: string; kind: SwapState };
  obsidianEnabled: boolean;
  speed: number;
  outSampleRate: number;

  // --- runtime ---
  phase: Phase;
  statusText: string;
  muted: boolean;
  paused: boolean;
  skipping: boolean;
  ended: boolean;

  // --- picker UI state ---
  sttSwapping: boolean;
  sttStatus: { text: string; kind: SwapState };
  voiceSwapping: boolean;
  voiceStatus: { text: string; kind: SwapState };
  modelStatus: { text: string; kind: SwapState };

  // --- transcripts ---
  userCaption: string;
  partialCaption: string; // live streaming ASR partial (Parakeet), pre-finalize
  aiSentences: string[];
  aiAccum: string;

  // --- mic input level ---
  micLevel: number;

  // --- prefs ---
  prefs: Prefs;

  // --- actions ---
  setSession: (config: Partial<AppState>) => void;
  setPhase: (phase: Phase) => void;
  setStatusText: (text: string) => void;
  setMuted: (muted: boolean) => void;
  setPaused: (paused: boolean) => void;
  setSkipping: (skipping: boolean) => void;
  setEnded: (ended: boolean) => void;
  setUserCaption: (text: string) => void;
  setPartialCaption: (text: string) => void;
  appendAiSentence: (text: string) => void;
  clearAiCaption: () => void;
  clearCaptions: () => void;
  setMicLevel: (level: number) => void;
  setSttSwapping: (s: boolean) => void;
  setSttStatus: (text: string, kind?: SwapState) => void;
  setVoiceSwapping: (s: boolean) => void;
  setVoiceStatus: (text: string, kind?: SwapState) => void;
  setModelStatus: (text: string, kind?: SwapState) => void;
  setSttModel: (model: string) => void;
  setSttEngine: (engine: string) => void;
  setTurnWaiting: (waiting: boolean) => void;
  setVoice: (voice: string) => void;
  setModel: (model: string) => void;
  setPersona: (name: string) => void;
  setPersonaStatus: (text: string, kind?: SwapState) => void;
  setToolsEnabled: (enabled: boolean) => void;
  setToolsAllowed: (allowed: string[]) => void;
  setInputMode: (mode: "vad" | "wake_word") => void;
  setInputModeStatus: (text: string, kind?: SwapState) => void;
  setSpeed: (speed: number) => void;
  patchPrefs: (patch: Partial<Prefs>) => void;
}

// Phase → status text. Mirrors the labels from the legacy app.js.
const PHASE_STATUS: Record<Phase, string> = {
  idle: "STANDBY",
  listening: "LISTENING",
  thinking: "ANALYZING",
  speaking: "TRANSMITTING",
};

const initialPrefs = loadPrefs();

export const useAppStore = create<AppState>((set, get) => ({
  sessionId: null,
  voice: null,
  voicesAvailable: [],
  model: null,
  modelsAvailable: [],
  sttEngine: null,
  sttEnginesAvailable: [],
  sttModel: null,
  sttModelsAvailable: [],
  turnEnabled: false,
  turnWaiting: false,
  persona: null,
  personasAvailable: [],
  personaStatus: { text: "", kind: "" },
  toolsEnabled: initialPrefs.toolsEnabled,
  toolsAvailable: [],
  toolsAllowed: [],
  inputMode: initialPrefs.inputMode,
  wakewordModel: null,
  wakewordDisplayName: null,
  inputModeStatus: { text: "", kind: "" },
  obsidianEnabled: false,
  speed: initialPrefs.speed,
  outSampleRate: 24000,

  phase: "idle",
  statusText: "CONNECTING",
  muted: false,
  paused: false,
  skipping: false,
  ended: false,

  sttSwapping: false,
  sttStatus: { text: "", kind: "" },
  voiceSwapping: false,
  voiceStatus: { text: "", kind: "" },
  modelStatus: { text: "", kind: "" },

  userCaption: "",
  partialCaption: "",
  aiSentences: [],
  aiAccum: "",

  micLevel: 0,

  prefs: initialPrefs,

  setSession: (partial) => set(partial as any),
  setPhase: (phase) => {
    const s = get();
    if (s.ended) return;
    if (s.paused && phase !== "idle") return;
    set({
      phase,
      statusText: PHASE_STATUS[phase] || phase.toUpperCase(),
      skipping: s.skipping && phase === "idle" ? false : s.skipping,
    });
  },
  setStatusText: (statusText) => set({ statusText }),
  setMuted: (muted) => set({ muted }),
  setPaused: (paused) => set({ paused }),
  setSkipping: (skipping) => set({ skipping }),
  setEnded: (ended) => set({ ended }),
  setUserCaption: (text) => set({ userCaption: text }),
  setPartialCaption: (text) => set({ partialCaption: text }),
  appendAiSentence: (text) => {
    if (!text) return;
    const cur = get();
    const sentences = [...cur.aiSentences, text];
    const accum = cur.aiAccum ? cur.aiAccum + " " + text : text;
    set({ aiSentences: sentences, aiAccum: accum });
  },
  clearAiCaption: () => set({ aiSentences: [], aiAccum: "" }),
  clearCaptions: () =>
    set({ userCaption: "", partialCaption: "", aiSentences: [], aiAccum: "" }),
  setMicLevel: (micLevel) => set({ micLevel }),
  setSttSwapping: (sttSwapping) => set({ sttSwapping }),
  setSttStatus: (text, kind = "") => set({ sttStatus: { text, kind } }),
  setVoiceSwapping: (voiceSwapping) => set({ voiceSwapping }),
  setVoiceStatus: (text, kind = "") => set({ voiceStatus: { text, kind } }),
  setModelStatus: (text, kind = "") => set({ modelStatus: { text, kind } }),
  setSttModel: (sttModel) => set({ sttModel }),
  setSttEngine: (sttEngine) => set({ sttEngine }),
  setTurnWaiting: (turnWaiting) => set({ turnWaiting }),
  setVoice: (voice) => set({ voice }),
  setModel: (model) => set({ model }),
  setPersona: (persona) => set({ persona }),
  setPersonaStatus: (text, kind = "") => set({ personaStatus: { text, kind } }),
  setToolsEnabled: (toolsEnabled) => set({ toolsEnabled }),
  setToolsAllowed: (toolsAllowed) => set({ toolsAllowed }),
  setInputMode: (inputMode) => set({ inputMode }),
  setInputModeStatus: (text, kind = "") =>
    set({ inputModeStatus: { text, kind } }),
  setSpeed: (speed) => set({ speed }),
  patchPrefs: (patch) => {
    const next = { ...get().prefs, ...patch };
    set({ prefs: next });
    savePrefs(next);
  },
}));

export function patchPrefs(patch: Partial<Prefs>) {
  useAppStore.getState().patchPrefs(patch);
}
