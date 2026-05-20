// Centered floating settings modal with mic / STT / LLM / voice pickers,
// speed buttons, orb-size slider, and toggles. All picker actions flow through
// callbacks injected by App.tsx so the WS sends live in one place.

import { useEffect, useState } from "react";
import { useAppStore } from "../state/store";
import { Picker, PickerOption } from "./Picker";
import { CloseIcon } from "./icons";

// Display labels for the STT picker. Keys must stay in sync with
// SUPPORTED_MODELS in local_tts/stt/transcriber.py.
const STT_MODEL_LABELS: Record<string, string> = {
  tiny: "Tiny — fastest (<300ms), low accuracy",
  base: "Base — fast (~300ms)",
  small: "Small — fast + decent (~300-500ms)",
  medium: "Medium — balanced (~500-800ms)",
  "large-v3-turbo": "Large v3 Turbo — accurate (~700-1100ms)",
  "large-v3": "Large v3 — max accuracy (~1500-2500ms)",
};

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
  onSwapStt: (model: string) => void;
  onSwapVoice: (voice: string) => void;
  onSwapModel: (model: string) => void;
  onSpeedChange: (speed: number) => void;
  onMicChange: (deviceId: string | null) => void;
  onToggleTools: (value: boolean) => void;
  onToggleTool: (tool: string, value: boolean) => void;
  onSwapPersona: (name: string) => void;
  onSubmitCustomPersona: (prompt: string) => void;
}

export function SettingsModal({
  open,
  onClose,
  onSwapStt,
  onSwapVoice,
  onSwapModel,
  onSpeedChange,
  onMicChange,
  onToggleTools,
  onToggleTool,
  onSwapPersona,
  onSubmitCustomPersona,
}: SettingsModalProps) {
  const sttModel = useAppStore((s) => s.sttModel);
  const sttModelsAvailable = useAppStore((s) => s.sttModelsAvailable);
  const sttStatus = useAppStore((s) => s.sttStatus);
  const sttSwapping = useAppStore((s) => s.sttSwapping);

  const voice = useAppStore((s) => s.voice);
  const voicesAvailable = useAppStore((s) => s.voicesAvailable);
  const voiceStatus = useAppStore((s) => s.voiceStatus);
  const voiceSwapping = useAppStore((s) => s.voiceSwapping);

  const model = useAppStore((s) => s.model);
  const modelsAvailable = useAppStore((s) => s.modelsAvailable);
  const modelStatus = useAppStore((s) => s.modelStatus);

  const speed = useAppStore((s) => s.speed);
  const prefs = useAppStore((s) => s.prefs);
  const patchPrefs = useAppStore((s) => s.patchPrefs);

  const toolsEnabled = useAppStore((s) => s.toolsEnabled);
  const toolsAvailable = useAppStore((s) => s.toolsAvailable);
  const toolsAllowed = useAppStore((s) => s.toolsAllowed);

  const persona = useAppStore((s) => s.persona);
  const personasAvailable = useAppStore((s) => s.personasAvailable);
  const personaStatus = useAppStore((s) => s.personaStatus);

  const [customPromptDraft, setCustomPromptDraft] = useState<string>(
    prefs.customPersonaPrompt || "",
  );
  useEffect(() => {
    setCustomPromptDraft(prefs.customPersonaPrompt || "");
  }, [prefs.customPersonaPrompt]);

  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [currentMicId, setCurrentMicId] = useState<string>("");

  useEffect(() => {
    if (!open) return;
    if (!navigator.mediaDevices?.enumerateDevices) return;
    let cancelled = false;
    (async () => {
      try {
        const devs = await navigator.mediaDevices.enumerateDevices();
        if (cancelled) return;
        setMics(devs.filter((d) => d.kind === "audioinput"));
      } catch {
        /* */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  // Listen for hot-plugged devices.
  useEffect(() => {
    if (!navigator.mediaDevices?.addEventListener) return;
    const refresh = async () => {
      try {
        const devs = await navigator.mediaDevices.enumerateDevices();
        setMics(devs.filter((d) => d.kind === "audioinput"));
      } catch {
        /* */
      }
    };
    navigator.mediaDevices.addEventListener("devicechange", refresh);
    return () => {
      navigator.mediaDevices.removeEventListener("devicechange", refresh);
    };
  }, []);

  // Compute the mic select's current value.
  const micValue =
    (prefs.micId && mics.some((d) => d.deviceId === prefs.micId)
      ? prefs.micId
      : "") || "";

  const sttOptions: PickerOption[] = sttModelsAvailable.map((name) => ({
    value: name,
    label: STT_MODEL_LABELS[name] || name,
  }));
  const voiceOptions: PickerOption[] = voicesAvailable.map((v) => ({
    value: v.id,
    label: v.label,
  }));
  const modelOptions: PickerOption[] = modelsAvailable.map((name) => ({
    value: name,
    label: name,
  }));

  const handleSpeed = (next: number) => {
    onSpeedChange(next);
  };

  const handleOrbSize = (e: React.ChangeEvent<HTMLInputElement>) => {
    const size = parseInt(e.target.value, 10);
    document.documentElement.style.setProperty("--orb-size", size + "px");
    patchPrefs({ orbSize: size });
  };

  return (
    <>
      <div
        id="settings-backdrop"
        className="settings-backdrop"
        hidden={!open}
        onClick={onClose}
      />
      <div id="settings-panel" className="settings-panel" hidden={!open}>
        <div className="settings-header">
          <span className="settings-title">Settings</span>
          <button
            id="settings-close"
            className="settings-close"
            type="button"
            aria-label="Close settings"
            onClick={onClose}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="settings-grid">
          <div className="settings-row">
            <label htmlFor="mic-select">Microphone</label>
            <select
              id="mic-select"
              value={micValue}
              onChange={(e) => onMicChange(e.target.value || null)}
            >
              <option value="">System default</option>
              {mics.map((d) => (
                <option key={d.deviceId} value={d.deviceId}>
                  {d.label || `Microphone (${d.deviceId.slice(0, 6)})`}
                </option>
              ))}
            </select>
          </div>

          <Picker
            label="Speech Recognition"
            options={sttOptions}
            value={sttModel}
            disabled={sttSwapping}
            status={sttStatus}
            onChange={onSwapStt}
          />

          <Picker
            label="LLM Model"
            options={modelOptions}
            value={model}
            status={modelStatus}
            onChange={onSwapModel}
          />

          <Picker
            label="Voice"
            options={voiceOptions}
            value={voice}
            disabled={voiceSwapping}
            status={voiceStatus}
            onChange={onSwapVoice}
          />

          <div className="settings-row settings-span">
            <label>Speech Speed</label>
            <div
              className="speed-picker"
              id="speed-picker"
              role="group"
              aria-label="Speech speed"
            >
              {[
                { v: 0.85, label: "Slow" },
                { v: 1.0, label: "Medium" },
                { v: 1.2, label: "Fast" },
              ].map((s) => (
                <button
                  key={s.v}
                  className={`speed-btn ${speed === s.v ? "active" : ""}`}
                  type="button"
                  onClick={() => handleSpeed(s.v)}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          <div className="settings-row">
            <label htmlFor="orb-size">Orb size</label>
            <div className="range-row">
              <input
                id="orb-size"
                type="range"
                min={120}
                max={380}
                step={10}
                value={prefs.orbSize}
                onChange={handleOrbSize}
              />
              <span id="orb-size-val" className="settings-val">
                {prefs.orbSize}
              </span>
            </div>
          </div>

          <div className="settings-row settings-toggles">
            <label className="toggle-item">
              <input
                id="show-meter"
                type="checkbox"
                checked={prefs.showMeter}
                onChange={(e) => patchPrefs({ showMeter: e.target.checked })}
              />
              <span>Mic meter</span>
            </label>
            <label className="toggle-item">
              <input
                id="show-captions"
                type="checkbox"
                checked={prefs.showCaptions}
                onChange={(e) =>
                  patchPrefs({ showCaptions: e.target.checked })
                }
              />
              <span>Captions</span>
            </label>
          </div>

          {personasAvailable.length > 0 ? (
            <Picker
              label="Persona"
              options={personasAvailable.map((p) => ({ value: p, label: p }))}
              value={persona}
              status={personaStatus}
              onChange={onSwapPersona}
            />
          ) : null}

          {persona === "custom" ? (
            <div className="settings-row settings-span">
              <label>
                Custom system prompt
                <span className="settings-hint">
                  saved per browser; takes effect on Save
                </span>
              </label>
              <textarea
                value={customPromptDraft}
                onChange={(e) => setCustomPromptDraft(e.target.value)}
                rows={4}
                style={{
                  width: "100%",
                  background: "var(--panel)",
                  color: "var(--text)",
                  border: "1px solid var(--panel-border)",
                  borderRadius: 8,
                  padding: "8px 10px",
                  fontFamily: "inherit",
                  fontSize: 13,
                  resize: "vertical",
                }}
              />
              <button
                type="button"
                onClick={() => onSubmitCustomPersona(customPromptDraft)}
                disabled={!customPromptDraft.trim()}
                style={{
                  marginTop: 6,
                  alignSelf: "flex-end",
                  background: "var(--accent)",
                  color: "var(--bg)",
                  border: "none",
                  borderRadius: 6,
                  padding: "6px 12px",
                  fontSize: 12,
                  cursor: "pointer",
                }}
              >
                Save persona
              </button>
            </div>
          ) : null}

          {toolsAvailable.length > 0 ? (
            <div className="settings-row settings-span">
              <label>
                Internet research
                <span className="settings-hint">
                  {toolsEnabled
                    ? "the assistant can call tools and search the web"
                    : "off — local model only"}
                </span>
              </label>
              <div className="settings-toggles">
                <label className="toggle-item">
                  <input
                    type="checkbox"
                    checked={toolsEnabled}
                    onChange={(e) => onToggleTools(e.target.checked)}
                  />
                  <span>Enable tools</span>
                </label>
                {toolsAvailable.map((tool) => (
                  <label key={tool} className="toggle-item">
                    <input
                      type="checkbox"
                      checked={toolsAllowed.includes(tool)}
                      disabled={!toolsEnabled}
                      onChange={(e) => onToggleTool(tool, e.target.checked)}
                    />
                    <span>{tool}</span>
                  </label>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}
