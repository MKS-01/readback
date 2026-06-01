// Inline meta row of feature chips. Surfaces every runtime-switchable state
// (voice, model, persona, tools, obsidian) so the user can see at a glance
// what's active without opening Settings. Every chip is clickable — opens
// Settings so the relevant row is one tap away.
//
// Note: the `mode` (VAD / Wake-word) chip is intentionally omitted until the
// wake-word UI is brought back. Backend code still exists in
// `local_tts/wakeword/` but the picker has been hidden.

import { useAppStore } from "../state/store";

function prettyVoice(voice: string | null): string {
  if (!voice) return "…";
  // Strip any legacy Kokoro `af_`/`bm_` prefix, then title-case Qwen speaker
  // ids like `uncle_fu` → "Uncle Fu".
  const stripped = voice.replace(/^[abefhijpz][fm]_/, "");
  return stripped
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

interface ChipProps {
  label: string;
  value: string;
  state?: "on" | "off" | "neutral";
  onClick: () => void;
}

function Chip({ label, value, state = "neutral", onClick }: ChipProps) {
  const stateColor =
    state === "on" ? "var(--accent)" : state === "off" ? "var(--text-mute)" : undefined;
  return (
    <button
      type="button"
      className="meta-item"
      onClick={onClick}
      style={{
        background: "none",
        border: "none",
        padding: "4px 0",
        cursor: "pointer",
        font: "inherit",
        color: "inherit",
      }}
    >
      <span className="meta-label">{label}</span>
      <span
        className="meta-value"
        style={stateColor ? { color: stateColor } : undefined}
      >
        {value}
      </span>
    </button>
  );
}

interface HeaderProps {
  onOpenSettings: () => void;
}

export function Header({ onOpenSettings }: HeaderProps) {
  const voice = useAppStore((s) => s.voice);
  const model = useAppStore((s) => s.model);
  const persona = useAppStore((s) => s.persona);
  const toolsEnabled = useAppStore((s) => s.toolsEnabled);
  const obsidianEnabled = useAppStore((s) => s.obsidianEnabled);

  return (
    <header className="hdr">
      <div className="hdr-meta">
        <Chip label="voice" value={prettyVoice(voice)} onClick={onOpenSettings} />
        <span className="meta-div" aria-hidden="true" />
        <Chip label="model" value={model || "…"} onClick={onOpenSettings} />
        <span className="meta-div" aria-hidden="true" />
        <Chip
          label="persona"
          value={(persona || "…").toUpperCase()}
          onClick={onOpenSettings}
        />
        <span className="meta-div" aria-hidden="true" />
        <Chip
          label="tools"
          value={toolsEnabled ? "ON" : "OFF"}
          state={toolsEnabled ? "on" : "off"}
          onClick={onOpenSettings}
        />
        <span className="meta-div" aria-hidden="true" />
        <Chip
          label="vault"
          value={obsidianEnabled ? "ON" : "OFF"}
          state={obsidianEnabled ? "on" : "off"}
          onClick={onOpenSettings}
        />
      </div>
    </header>
  );
}
