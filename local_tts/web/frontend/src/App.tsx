// Article reader. Paste a URL → the server fetches, optionally summarizes, and
// synthesizes the whole piece offline, then streams progress and hands back an
// audio URL we play in-page (and offer for download). The three.js orb is reused
// as the working/playing visual (driven by store.phase).

import { useEffect, useRef, useState } from "react";
import { AudioPlayer } from "./components/AudioPlayer";
import { ArrowIcon, CopyIcon } from "./components/icons";
import { OrbContainer } from "./components/OrbContainer";
import { PickerOption } from "./components/Picker";
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
  const [showTranscript, setShowTranscript] = useState(false);
  const [copied, setCopied] = useState(false);

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
            text: msg.text,
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
    setShowTranscript(false);
    setCopied(false);
    st.setBusy(true);
    st.setPhase("thinking", "Starting…");
    wsRef.current?.send({
      type: "read",
      url: u,
      mode: prefs.mode,
      voice: prefs.voice || undefined,
    });
  };

  const onCancel = () => {
    wsRef.current?.send({ type: "cancel" });
    const st = useAppStore.getState();
    st.setBusy(false);
    st.setProgress(null);
    st.setStatus("");
    st.setPhase("idle", "");
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

      <div className="reader-center">
        <OrbContainer />

        <main className="reader-panel">
        {busy ? (
          <div className="reader-busy">
            <span className="reader-busy-text">{statusText || "Working…"}</span>
            <span className={`reader-bar ${progress ? "" : "indet"}`}>
              <span
                className="reader-bar-fill"
                style={progress ? { width: `${pct}%` } : undefined}
              />
            </span>
            <button type="button" className="reader-cancel" onClick={onCancel}>
              Cancel
            </button>
          </div>
        ) : (
        <>
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
          />
          <button
            className="reader-go"
            type="button"
            onClick={onRead}
            disabled={!url.trim()}
            aria-label="Read"
          >
            <ArrowIcon size={18} />
          </button>
        </div>

        <div className="reader-controls">
          <div className="seg" role="group" aria-label="read mode">
            {(["full", "summary"] as const).map((m) => (
              <button
                key={m}
                type="button"
                className={`seg-btn ${prefs.mode === m ? "active" : ""}`}
                onClick={() => patchPrefs({ mode: m })}
              >
                {m === "full" ? "Full article" : "Summary"}
              </button>
            ))}
          </div>
          {voiceOptions.length > 0 ? (
            <select
              className="reader-select"
              aria-label="Voice"
              value={prefs.voice || ""}
              onChange={(e) => patchPrefs({ voice: e.target.value })}
            >
              {voiceOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          ) : null}
        </div>

        {error ? <div className="reader-error">{error}</div> : null}

        {result ? (
          <div className="reader-result">
            <div className="reader-title">{result.title}</div>
            <div className="reader-result-meta">
              {result.mode === "summary" ? "Summary" : "Full"} ·{" "}
              {result.wordCount.toLocaleString()} words ·{" "}
              {fmtDuration(result.durationSec)}
            </div>
            <AudioPlayer
              src={result.audioUrl}
              duration={result.durationSec}
              onPlay={() => useAppStore.getState().setPhase("speaking")}
              onPause={() => useAppStore.getState().setPhase("idle")}
              onEnded={() => useAppStore.getState().setPhase("idle")}
            />

            {result.text ? (
              <div className="reader-transcript">
                <div className="reader-transcript-head">
                  <button
                    type="button"
                    className="reader-transcript-toggle"
                    onClick={() => setShowTranscript((v) => !v)}
                    aria-expanded={showTranscript}
                  >
                    {showTranscript ? "Hide transcript" : "Show transcript"}
                  </button>
                  {showTranscript ? (
                    <button
                      type="button"
                      className="reader-transcript-copy"
                      onClick={() => {
                        navigator.clipboard
                          ?.writeText(result.text || "")
                          .then(() => {
                            setCopied(true);
                            setTimeout(() => setCopied(false), 1500);
                          })
                          .catch(() => {});
                      }}
                    >
                      <CopyIcon size={13} />
                      {copied ? "Copied" : "Copy"}
                    </button>
                  ) : null}
                </div>
                {showTranscript ? (
                  <div className="reader-transcript-text">{result.text}</div>
                ) : null}
              </div>
            ) : null}

            <a className="reader-download" href={result.audioUrl} download>
              ↓ Download audio
            </a>
          </div>
        ) : null}
        </>
        )}
        </main>
      </div>
    </div>
  );
}
