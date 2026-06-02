// Top-level wiring. Owns the AudioEngine + WSClient singletons, plugs the WS
// message router into the store, and dispatches user actions back through WS.
//
// React only handles the "view" — the audio queue, mic worklet, and three.js
// brain are imperative inside refs/effects so the 60fps animation loops never
// re-render anything.

import { useCallback, useEffect, useRef, useState } from "react";
import { AudioEngine } from "./lib/audioEngine";
import { FreqBuffer } from "./lib/brain";
import { WSClient, WSMessage } from "./lib/ws";
import { useAppStore } from "./state/store";
import { OrbContainer, OrbHandle } from "./components/OrbContainer";
import { Header } from "./components/Header";
import { Captions } from "./components/Captions";
import { MicMeter } from "./components/MicMeter";
import { Dock } from "./components/Dock";
import { TypePopover } from "./components/TypePopover";
import { SettingsModal } from "./components/SettingsModal";

export default function App() {
  const orbRef = useRef<OrbHandle | null>(null);
  const wsRef = useRef<WSClient | null>(null);
  const engineRef = useRef<AudioEngine | null>(null);

  const [typeOpen, setTypeOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // ------------------------------------------------------------------
  // Apply prefs (theme + orb size + show/hide) on every change.
  // ------------------------------------------------------------------
  const prefs = useAppStore((s) => s.prefs);
  useEffect(() => {
    document.documentElement.style.setProperty(
      "--orb-size",
      prefs.orbSize + "px",
    );
  }, [prefs.orbSize]);

  useEffect(() => {
    document.body.classList.remove("theme-ghost");
    document.body.classList.add(`theme-${prefs.theme || "ghost"}`);
  }, [prefs.theme]);

  // ------------------------------------------------------------------
  // WS message router.
  // ------------------------------------------------------------------
  const handleControl = useCallback((msg: WSMessage) => {
    const store = useAppStore.getState();
    switch (msg.type) {
      case "config": {
        const patch: Record<string, any> = {};
        if (msg.session_id) patch.sessionId = msg.session_id;
        if (msg.voice) patch.voice = msg.voice;
        if (msg.model) patch.model = msg.model;
        if (msg.output_sample_rate) patch.outSampleRate = msg.output_sample_rate;
        if (msg.voices_available) patch.voicesAvailable = msg.voices_available;
        if (msg.stt_engine) patch.sttEngine = msg.stt_engine;
        if (msg.stt_engines_available)
          patch.sttEnginesAvailable = msg.stt_engines_available;
        if (msg.stt_model) patch.sttModel = msg.stt_model;
        if (msg.stt_models_available)
          patch.sttModelsAvailable = msg.stt_models_available;
        if (typeof msg.turn_enabled === "boolean")
          patch.turnEnabled = msg.turn_enabled;
        if (msg.models_available) patch.modelsAvailable = msg.models_available;
        if (msg.persona) patch.persona = msg.persona;
        if (msg.personas_available)
          patch.personasAvailable = msg.personas_available;
        if (typeof msg.tools_enabled === "boolean")
          patch.toolsEnabled = msg.tools_enabled;
        if (msg.tools_available) patch.toolsAvailable = msg.tools_available;
        if (msg.tools_allowed) patch.toolsAllowed = msg.tools_allowed;
        if (msg.input_mode) patch.inputMode = msg.input_mode;
        if (msg.wakeword_model) patch.wakewordModel = msg.wakeword_model;
        if (msg.wakeword_display_name)
          patch.wakewordDisplayName = msg.wakeword_display_name;
        if (typeof msg.obsidian_enabled === "boolean")
          patch.obsidianEnabled = msg.obsidian_enabled;
        if (typeof msg.speed === "number") {
          patch.speed = msg.speed;
        }
        store.setSession(patch);

        // Re-emit saved prefs that diverge from server-side defaults.
        const p = store.prefs;
        if (
          p.sttEngine &&
          p.sttEngine !== msg.stt_engine &&
          msg.stt_engines_available?.includes(p.sttEngine)
        ) {
          wsRef.current?.send({ type: "set_stt_engine", engine: p.sttEngine });
          store.setSttSwapping(true);
          store.setSttStatus("loading…", "loading");
        }
        if (
          p.sttModel &&
          p.sttModel !== msg.stt_model &&
          msg.stt_models_available?.includes(p.sttModel)
        ) {
          wsRef.current?.send({ type: "set_stt_model", model: p.sttModel });
          store.setSttSwapping(true);
          store.setSttStatus("loading…", "loading");
        }
        if (
          p.voice &&
          p.voice !== msg.voice &&
          (msg.voices_available || []).some((v: any) => v.id === p.voice)
        ) {
          wsRef.current?.send({ type: "set_voice", voice: p.voice });
          store.setVoiceSwapping(true);
          store.setVoiceStatus("loading…", "loading");
        }
        if (p.speed !== 1.0) {
          wsRef.current?.send({ type: "set_speed", speed: p.speed });
        }
        break;
      }
      case "model":
        if (msg.state === "unloading") {
          store.setModelStatus("unloading…", "loading");
        } else {
          store.setModel(msg.model);
          store.setModelStatus("ready", "ready");
          window.setTimeout(() => store.setModelStatus("", ""), 1400);
        }
        break;
      case "stt_model":
        if (msg.state === "loading") {
          store.setSttSwapping(true);
          store.setSttStatus(`loading ${msg.model}…`, "loading");
        } else if (msg.state === "ready") {
          store.setSttSwapping(false);
          store.setSttModel(msg.model);
          store.setSttStatus("ready", "ready");
          store.patchPrefs({ sttModel: msg.model });
          window.setTimeout(() => store.setSttStatus("", ""), 1400);
        } else if (msg.state === "error") {
          store.setSttSwapping(false);
          store.setSttStatus(msg.message || "swap failed", "error");
        }
        break;
      case "stt_engine":
        if (msg.state === "loading") {
          store.setSttSwapping(true);
          store.setSttStatus(`loading ${msg.engine}…`, "loading");
        } else if (msg.state === "ready") {
          store.setSttSwapping(false);
          store.setSttEngine(msg.engine);
          const enginePatch: Record<string, any> = {};
          if (Array.isArray(msg.models_available))
            enginePatch.sttModelsAvailable = msg.models_available;
          if (msg.model) enginePatch.sttModel = msg.model;
          store.setSession(enginePatch);
          store.setSttStatus("ready", "ready");
          store.patchPrefs({ sttEngine: msg.engine });
          window.setTimeout(() => store.setSttStatus("", ""), 1400);
        } else if (msg.state === "error") {
          store.setSttSwapping(false);
          store.setSttStatus(msg.message || "engine switch failed", "error");
        }
        break;
      case "turn":
        // Smart-Turn said the pause is mid-thought — surface "still listening".
        store.setTurnWaiting(msg.state === "waiting");
        break;
      case "voice":
        if (msg.state === "loading") {
          store.setVoiceSwapping(true);
          store.setVoiceStatus("loading…", "loading");
        } else if (msg.state === "ready") {
          store.setVoiceSwapping(false);
          store.setVoice(msg.voice);
          store.setVoiceStatus("ready", "ready");
          store.patchPrefs({ voice: msg.voice });
          window.setTimeout(() => store.setVoiceStatus("", ""), 1400);
        } else if (msg.state === "error") {
          store.setVoiceSwapping(false);
          store.setVoiceStatus(msg.message || "swap failed", "error");
        }
        break;
      case "phase":
        store.setPhase(msg.value);
        // Reset scale when leaving speaking phase.
        if (msg.value !== "speaking") {
          orbRef.current?.brain?.setScale(1);
        }
        // A short/aborted utterance ends at idle with no final transcript —
        // drop any lingering live partial so it doesn't stick on screen.
        if (msg.value === "idle") {
          store.setPartialCaption("");
        }
        // "still listening" only applies during a listening pause.
        if (msg.value !== "listening") {
          store.setTurnWaiting(false);
        }
        break;
      case "partial":
        // Live streaming ASR (Parakeet): replace-in-place while the user speaks.
        store.setPartialCaption(msg.text);
        break;
      case "transcript":
        if (msg.role === "user") {
          store.clearAiCaption();
          store.setPartialCaption(""); // promote partial → final
          store.setUserCaption(msg.text);
        } else {
          if (store.skipping) break;
          store.appendAiSentence(msg.text);
        }
        break;
      case "level":
        store.setMicLevel(msg.value);
        if (store.phase === "idle" || store.phase === "listening") {
          orbRef.current?.brain?.setScale(
            1 + Math.min(0.18, msg.value * 1.4),
          );
        }
        break;
      case "tools_enabled":
        store.setToolsEnabled(!!msg.value);
        store.patchPrefs({ toolsEnabled: !!msg.value });
        break;
      case "tools_allowed":
        if (Array.isArray(msg.value)) {
          store.setToolsAllowed(msg.value);
        }
        break;
      case "persona":
        if (msg.state === "ready") {
          store.setPersona(msg.name);
          store.setPersonaStatus("ready", "ready");
          store.patchPrefs({ persona: msg.name });
          if (Array.isArray(msg.personas_available)) {
            store.setSession({ personasAvailable: msg.personas_available });
          }
          window.setTimeout(() => store.setPersonaStatus("", ""), 1400);
        } else if (msg.state === "error") {
          store.setPersonaStatus(msg.message || "swap failed", "error");
        }
        break;
      case "input_mode":
        if (msg.state === "error") {
          store.setInputModeStatus(msg.message || "switch failed", "error");
          if (msg.value) store.setInputMode(msg.value);
        } else {
          store.setInputMode(msg.value);
          store.setInputModeStatus("ready", "ready");
          store.patchPrefs({ inputMode: msg.value });
          window.setTimeout(() => store.setInputModeStatus("", ""), 1400);
        }
        break;
      case "error":
        store.setStatusText("ERROR: " + msg.message);
        break;
    }
  }, []);

  // ------------------------------------------------------------------
  // Boot: connect WS, start mic, set up audio engine + playback RAF.
  // ------------------------------------------------------------------
  useEffect(() => {
    const engine = new AudioEngine({
      onMicFrame: (buf) => {
        wsRef.current?.sendBinary(buf);
      },
    });
    engineRef.current = engine;

    const store = useAppStore.getState();
    const ws = new WSClient({
      onControl: handleControl,
      onAudio: async (buf) => {
        if (store.skipping || store.paused) return;
        await engine.enqueueAudio(buf);
        // Kick off the analyser RAF the first time audio is queued.
        startPlaybackRaf();
      },
      onOpen: async () => {
        store.setStatusText("ONLINE");
        try {
          await engine.startMic(useAppStore.getState().prefs.micId);
        } catch (e) {
          console.error(e);
          // Fall back to system default if a saved deviceId no longer exists.
          if (useAppStore.getState().prefs.micId) {
            store.patchPrefs({ micId: null });
            try {
              await engine.startMic(null);
              return;
            } catch {
              /* */
            }
          }
          store.setStatusText("MIC PERMISSION DENIED");
        }
      },
      onClose: () => {
        if (!useAppStore.getState().ended) {
          store.setStatusText("DISCONNECTED");
        }
      },
      onError: () => {
        store.setStatusText("CONNECTION ERROR");
      },
    });
    wsRef.current = ws;
    // Tell the server when the TTS queue finishes playing so it can reopen the
    // mic only after the speaker tail is gone (anti speaker-bleed).
    engine.setOnDrained(() => ws.send({ type: "playback_done" }));
    ws.connect();

    return () => {
      ws.close();
      engine.stopMic();
      engine.stopAllPlayback();
      wsRef.current = null;
      engineRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ------------------------------------------------------------------
  // Playback RAF: feeds the analyser FFT into the brain while speaking.
  // ------------------------------------------------------------------
  const playbackRafRef = useRef(0);
  const freqBufRef = useRef<FreqBuffer | null>(null);
  const startPlaybackRaf = useCallback(() => {
    if (playbackRafRef.current) return; // already running
    const tick = () => {
      const engine = engineRef.current;
      const analyser = engine?.getAnalyser();
      if (!analyser) {
        playbackRafRef.current = requestAnimationFrame(tick);
        return;
      }
      if (
        !freqBufRef.current ||
        freqBufRef.current.length !== analyser.frequencyBinCount
      ) {
        freqBufRef.current = new Uint8Array(analyser.frequencyBinCount);
      }
      analyser.getByteFrequencyData(freqBufRef.current);

      const store = useAppStore.getState();
      if (store.phase === "speaking") {
        let sum = 0;
        for (let i = 0; i < freqBufRef.current.length; i++) {
          sum += freqBufRef.current[i];
        }
        const energy = sum / (freqBufRef.current.length * 255);
        orbRef.current?.brain?.setScale(1 + Math.min(0.32, energy * 2.6));
        orbRef.current?.brain?.setFreq(freqBufRef.current);
      }
      playbackRafRef.current = requestAnimationFrame(tick);
    };
    playbackRafRef.current = requestAnimationFrame(tick);
  }, []);

  // ------------------------------------------------------------------
  // visibilitychange + first-touch audio unlock.
  // ------------------------------------------------------------------
  useEffect(() => {
    const onVis = async () => {
      if (document.visibilityState === "visible") {
        await engineRef.current?.unlockOutCtx();
      }
    };
    document.addEventListener("visibilitychange", onVis);
    const unlock = () => engineRef.current?.unlockOutCtx();
    document.addEventListener("touchstart", unlock, {
      once: true,
      passive: true,
    });
    document.addEventListener("click", unlock, { once: true });
    return () => {
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  // ------------------------------------------------------------------
  // User actions: dock buttons + text input + settings.
  // ------------------------------------------------------------------
  const send = (msg: WSMessage) => wsRef.current?.send(msg);

  const onToggleMute = () => {
    const store = useAppStore.getState();
    const next = !store.muted;
    store.setMuted(next);
    engineRef.current?.setMuted(next);
    send({ type: next ? "mute" : "unmute" });
    store.setStatusText(next ? "MUTED" : "LISTENING");
  };

  const skipCurrent = () => {
    const store = useAppStore.getState();
    store.setSkipping(true);
    engineRef.current?.stopAllPlayback();
    send({ type: "interrupt" });
    store.clearAiCaption();
    store.setStatusText("SKIPPING");
  };

  const onToggleType = () => setTypeOpen((v) => !v);
  const closeType = () => setTypeOpen(false);
  const onSubmitText = (text: string) => {
    const store = useAppStore.getState();
    if (store.phase === "speaking" || store.phase === "thinking") {
      skipCurrent();
    }
    send({ type: "text_input", text });
  };

  const onTogglePause = async () => {
    const store = useAppStore.getState();
    if (store.ended) return;
    if (!store.paused) {
      store.setPaused(true);
      engineRef.current?.stopAllPlayback();
      send({ type: "interrupt" });
      engineRef.current?.stopMic();
      store.setPhase("idle");
      store.setStatusText("PAUSED");
      if (typeOpen) setTypeOpen(false);
      document.body.classList.add("paused");
    } else {
      store.setPaused(false);
      document.body.classList.remove("paused");
      try {
        await engineRef.current?.startMic(store.prefs.micId);
      } catch (e) {
        console.warn("[pause] resume mic failed:", e);
      }
      store.setStatusText(store.muted ? "MUTED" : "LISTENING");
    }
  };

  const onOpenSettings = () => setSettingsOpen(true);
  const onCloseSettings = () => setSettingsOpen(false);

  // Picker action dispatchers — split so SettingsModal stays agnostic of WS.
  const onSwapStt = (model: string) => {
    const store = useAppStore.getState();
    if (!model || model === store.sttModel) return;
    store.setSttSwapping(true);
    store.setSttStatus("loading…", "loading");
    send({ type: "set_stt_model", model });
  };

  const onSwapSttEngine = (engine: string) => {
    const store = useAppStore.getState();
    if (!engine || engine === store.sttEngine) return;
    store.setSttSwapping(true);
    store.setSttStatus(`loading ${engine}…`, "loading");
    send({ type: "set_stt_engine", engine });
  };

  const onSwapVoice = (voice: string) => {
    const store = useAppStore.getState();
    if (!voice || voice === store.voice) return;
    store.setVoiceSwapping(true);
    store.setVoiceStatus("loading…", "loading");
    send({ type: "set_voice", voice });
  };

  const onSwapModel = (model: string) => {
    const store = useAppStore.getState();
    if (!model || model === store.model) return;
    store.setModelStatus("switching…", "loading");
    send({ type: "set_model", model });
  };

  const onSpeedChange = (speed: number) => {
    const store = useAppStore.getState();
    store.setSpeed(speed);
    store.patchPrefs({ speed });
    send({ type: "set_speed", speed });
  };

  const onToggleTools = (value: boolean) => {
    send({ type: "set_tools_enabled", value });
  };

  const onToggleTool = (tool: string, value: boolean) => {
    send({ type: "set_tool_allowed", tool, value });
  };

  const onSwapPersona = (name: string) => {
    const store = useAppStore.getState();
    if (!name || name === store.persona) return;
    store.setPersonaStatus("loading…", "loading");
    send({ type: "set_persona", name });
  };

  const onSubmitCustomPersona = (prompt: string) => {
    const trimmed = prompt.trim();
    if (!trimmed) return;
    useAppStore.getState().setPersonaStatus("saving…", "loading");
    useAppStore.getState().patchPrefs({ customPersonaPrompt: trimmed });
    send({ type: "set_persona_custom_prompt", prompt: trimmed });
  };

  const onMicChange = async (deviceId: string | null) => {
    const store = useAppStore.getState();
    store.patchPrefs({ micId: deviceId });
    if (store.ended) return;
    engineRef.current?.stopMic();
    try {
      await engineRef.current?.startMic(deviceId);
      store.setStatusText(store.muted ? "MUTED" : "LISTENING");
    } catch (e: any) {
      console.error(e);
      store.setStatusText("MIC ERROR: " + (e?.message || ""));
    }
  };

  // Orb tap-to-interrupt (separate from button-driven Skip).
  const onOrbClick = () => {
    const store = useAppStore.getState();
    if (store.phase === "speaking" || store.phase === "thinking") {
      engineRef.current?.stopAllPlayback();
      send({ type: "interrupt" });
    }
  };

  // Caption/meter visibility classes mirror the legacy `hidden` toggle.
  useEffect(() => {
    const captionsEl = document.getElementById("captions");
    captionsEl?.classList.toggle("hidden", !prefs.showCaptions);
  }, [prefs.showCaptions]);

  return (
    <>
      <span id="timer" style={{ display: "none" }} aria-hidden="true">
        00:00
      </span>
      <span id="assistant-name" style={{ display: "none" }} aria-hidden="true">
        local-tts
      </span>

      <Header onOpenSettings={onOpenSettings} />

      <main className="stage" onClick={(e) => {
        // Tap-to-interrupt only fires for the orb itself, not its parent.
        const target = e.target as HTMLElement;
        if (target.closest("#orb")) onOrbClick();
      }}>
        <OrbContainer ref={orbRef} />
        <MicMeter />
        <Captions />
      </main>

      <SettingsModal
        open={settingsOpen}
        onClose={onCloseSettings}
        onSwapStt={onSwapStt}
        onSwapSttEngine={onSwapSttEngine}
        onSwapVoice={onSwapVoice}
        onSwapModel={onSwapModel}
        onSpeedChange={onSpeedChange}
        onMicChange={onMicChange}
        onToggleTools={onToggleTools}
        onToggleTool={onToggleTool}
        onSwapPersona={onSwapPersona}
        onSubmitCustomPersona={onSubmitCustomPersona}
      />

      <footer className="dock">
        <TypePopover
          open={typeOpen}
          onClose={closeType}
          onSubmit={onSubmitText}
        />
        <Dock
          onToggleMute={onToggleMute}
          onSkip={skipCurrent}
          onToggleType={onToggleType}
          onTogglePause={onTogglePause}
          onOpenSettings={onOpenSettings}
          typeOpen={typeOpen}
        />
      </footer>
    </>
  );
}
