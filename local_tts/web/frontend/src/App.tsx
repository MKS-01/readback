// Article reader. Paste a URL → the server fetches, optionally summarizes, and
// synthesizes the whole piece offline, then streams progress and hands back an
// audio URL we play in-page (and offer for download). The three.js orb is reused
// as the working/playing visual (driven by store.phase).

import { useEffect, useRef, useState } from "react";
import { OrbContainer } from "./components/OrbContainer";
import { Picker, PickerOption } from "./components/Picker";
import { WSClient, WSMessage } from "./lib/ws";
import { patchPrefs, useAppStore } from "./state/store";

const PHASE_LABEL: Record<string, string> = {
  loading: "Loading model…",
  fetching: "Fetching article…",
  summarizing: "Summarizing…",
  synthesizing: "Synthesizing audio…",
};

function fmtDuration(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export default function App() {
  const wsRef = useRef<WSClient | null>(null);
  const [url, setUrl] = useState("");

  const connected = useAppStore((s) => s.connected);
  const statusText = useAppStore((s) => s.statusText);
  const progress = useAppStore((s) => s.progress);
  const busy = useAppStore((s) => s.busy);
  const error = useAppStore((s) => s.error);
  const result = useAppStore((s) => s.result);
  const voicesAvailable = useAppStore((s) => s.voicesAvailable);
  const model = useAppStore((s) => s.model);
  const prefs = useAppStore((s) => s.prefs);

  useEffect(() => {
    const handleControl = (msg: WSMessage) => {
      const st = useAppStore.getState();
      switch (msg.type) {
        case "config":
          st.setSession({
            voicesAvailable: msg.voices_available || [],
            model: msg.model || "",
          });
          if (!st.prefs.voice && msg.voice) patchPrefs({ voice: msg.voice });
          break;
        case "phase":
          st.setPhase("thinking", PHASE_LABEL[msg.value] || msg.value);
          break;
        case "progress":
          st.setProgress({ done: msg.done, total: msg.total });
          st.setStatus(`Synthesizing audio… ${msg.done}/${msg.total}`);
          break;
        case "done":
          st.setResult({
            title: msg.title,
            audioUrl: msg.audio_url,
            durationSec: msg.duration_sec,
            wordCount: msg.word_count,
            mode: msg.mode,
          });
          st.setProgress(null);
          st.setBusy(false);
          st.setPhase("idle", "");
          break;
        case "error":
          st.setError(msg.message || "Something went wrong.");
          st.setProgress(null);
          st.setBusy(false);
          st.setPhase("idle", "");
          break;
      }
    };

    const st = useAppStore.getState();
    const ws = new WSClient({
      onOpen: () => st.setConnected(true),
      onClose: () => st.setConnected(false),
      onError: () => st.setConnected(false),
      onAudio: () => {},
      onControl: handleControl,
    });
    ws.connect();
    wsRef.current = ws;
    return () => ws.close();
  }, []);

  const onRead = () => {
    const u = url.trim();
    if (!u || busy) return;
    const st = useAppStore.getState();
    st.setError("");
    st.setResult(null);
    st.setProgress(null);
    st.setBusy(true);
    st.setPhase("thinking", "Starting…");
    wsRef.current?.send({
      type: "read",
      url: u,
      mode: prefs.mode,
      voice: prefs.voice || undefined,
    });
  };

  const voiceOptions: PickerOption[] = voicesAvailable.map((v) => ({
    value: v.id,
    label: v.label,
  }));
  const pct = progress
    ? Math.round((100 * progress.done) / Math.max(1, progress.total))
    : 0;

  return (
    <div className="reader-root">
      <header className="hdr">
        <div className="hdr-meta">
          <span className="meta-item">
            <span className="meta-label">app</span>
            <span className="meta-value">READER</span>
          </span>
          <span className="meta-div" aria-hidden="true" />
          <span className="meta-item">
            <span className="meta-label">model</span>
            <span className="meta-value">{model || "…"}</span>
          </span>
          <span className="meta-div" aria-hidden="true" />
          <span className="meta-item">
            <span className="meta-label">link</span>
            <span
              className="meta-value"
              style={{ color: connected ? "var(--accent)" : "var(--text-mute)" }}
            >
              {connected ? "ON" : "OFF"}
            </span>
          </span>
        </div>
      </header>

      <OrbContainer />

      <main className="reader-panel">
        <div className="reader-input-row">
          <input
            className="reader-url"
            type="url"
            inputMode="url"
            placeholder="Paste an article URL…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onRead();
            }}
            disabled={busy}
          />
          <button
            className="reader-go"
            type="button"
            onClick={onRead}
            disabled={busy || !url.trim()}
          >
            {busy ? "···" : "READ"}
          </button>
        </div>

        <div className="reader-controls">
          <div className="seg" role="group" aria-label="read mode">
            {(["full", "summary"] as const).map((m) => (
              <button
                key={m}
                type="button"
                className={`seg-btn ${prefs.mode === m ? "active" : ""}`}
                disabled={busy}
                onClick={() => patchPrefs({ mode: m })}
              >
                {m === "full" ? "Full article" : "Summary"}
              </button>
            ))}
          </div>
          {voiceOptions.length > 0 ? (
            <div className="reader-voice">
              <Picker
                label="Voice"
                options={voiceOptions}
                value={prefs.voice}
                disabled={busy}
                onChange={(v) => patchPrefs({ voice: v })}
              />
            </div>
          ) : null}
        </div>

        {busy || statusText ? (
          <div className="reader-status">
            <span className="reader-status-text">{statusText}</span>
            {progress ? (
              <span className="reader-bar">
                <span className="reader-bar-fill" style={{ width: `${pct}%` }} />
              </span>
            ) : null}
          </div>
        ) : null}

        {error ? <div className="reader-error">{error}</div> : null}

        {result ? (
          <div className="reader-result">
            <div className="reader-title">{result.title}</div>
            <div className="reader-result-meta">
              {result.mode === "summary" ? "Summary" : "Full"} ·{" "}
              {result.wordCount.toLocaleString()} words ·{" "}
              {fmtDuration(result.durationSec)}
            </div>
            <audio
              className="reader-audio"
              controls
              autoPlay
              src={result.audioUrl}
              onPlay={() => useAppStore.getState().setPhase("speaking")}
              onPause={() => useAppStore.getState().setPhase("idle")}
              onEnded={() => useAppStore.getState().setPhase("idle")}
            />
            <a className="reader-download" href={result.audioUrl} download>
              ↓ Download audio
            </a>
          </div>
        ) : null}
      </main>
    </div>
  );
}
