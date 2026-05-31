// Bottom dock: [Mute · Skip · Type · Pause · ⚙]. Status text appears below
// the pill (e.g. LISTENING). Each button reads/writes the store and triggers
// callbacks exposed by App.tsx for side effects (WS send, mic restart, etc.).

import { useAppStore } from "../state/store";
import {
  MicIcon,
  PauseIcon,
  ResumeIcon,
  SettingsIcon,
  SkipIcon,
  TypeIcon,
} from "./icons";

interface DockProps {
  onToggleMute: () => void;
  onSkip: () => void;
  onToggleType: () => void;
  onTogglePause: () => void;
  onOpenSettings: () => void;
  typeOpen: boolean;
}

export function Dock({
  onToggleMute,
  onSkip,
  onToggleType,
  onTogglePause,
  onOpenSettings,
  typeOpen,
}: DockProps) {
  const muted = useAppStore((s) => s.muted);
  const paused = useAppStore((s) => s.paused);
  const phase = useAppStore((s) => s.phase);
  const statusText = useAppStore((s) => s.statusText);
  const skipDisabled = !(phase === "speaking" || phase === "thinking");

  return (
    <>
      <div className="dock-pill">
        <button
          id="mute-btn"
          className={`dock-btn ${muted ? "muted" : ""}`}
          type="button"
          aria-label={muted ? "Unmute microphone" : "Mute microphone"}
          onClick={onToggleMute}
          disabled={paused}
        >
          <MicIcon />
          <span>{muted ? "Unmute" : "Mute"}</span>
        </button>
        <span className="dock-sep" />
        <button
          id="skip-btn"
          className="dock-btn skip"
          type="button"
          aria-label="Skip current response"
          onClick={onSkip}
          disabled={skipDisabled}
        >
          <SkipIcon />
          <span>Skip</span>
        </button>
        <span className="dock-sep" />
        <button
          id="type-btn"
          className={`dock-btn type ${typeOpen ? "active" : ""}`}
          type="button"
          aria-label="Type a message"
          onClick={onToggleType}
          disabled={paused}
        >
          <TypeIcon />
          <span>Type</span>
        </button>
        <span className="dock-sep" />
        <button
          id="end-btn"
          className={`dock-btn end ${paused ? "paused" : ""}`}
          type="button"
          aria-label={paused ? "Resume call" : "Pause call"}
          onClick={onTogglePause}
        >
          {paused ? <ResumeIcon /> : <PauseIcon />}
          <span>{paused ? "Resume" : "Pause"}</span>
        </button>
        <span className="dock-sep" />
        <button
          id="settings-btn"
          className="dock-btn"
          type="button"
          aria-label="Open settings"
          onClick={onOpenSettings}
        >
          <SettingsIcon />
        </button>
      </div>
      <div className="dock-foot" id="dock-foot">
        <span id="status-text">{statusText}</span>
      </div>
    </>
  );
}
