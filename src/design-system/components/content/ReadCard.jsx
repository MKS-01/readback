import React, { useState, useRef, useEffect } from "react";
import { Badge } from "../feedback/Badge.jsx";
import { SeekBar } from "../player/SeekBar.jsx";

/**
 * readback ReadCard — a single saved read in the library. Click play to expand
 * the seek bar; in Summary mode the snippet becomes a word-synced karaoke
 * transcript (spoken words accent-blue). Self-driving demo clock.
 */
function fmt(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function ReadCard({
  title,
  date,
  duration = 111,
  mode = "summary", // "summary" | "full"
  voice = "codeword",
  words = 0,
  snippet = "",
  sourceUrl = "#",
  style = {},
}) {
  const [active, setActive] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [t, setT] = useState(0);
  const raf = useRef(null);
  const last = useRef(null);

  useEffect(() => {
    if (!playing) return;
    const tick = (now) => {
      if (last.current == null) last.current = now;
      const dt = (now - last.current) / 1000;
      last.current = now;
      setT((p) => {
        const n = p + dt;
        if (n >= duration) { setPlaying(false); return duration; }
        return n;
      });
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf.current); last.current = null; };
  }, [playing, duration]);

  const onPlay = () => {
    if (!active) { setActive(true); setPlaying(true); return; }
    if (t >= duration) { setT(0); setPlaying(true); return; }
    setPlaying((p) => !p);
  };

  const isSummary = mode === "summary";
  const playIcon = active && t >= duration ? "↺" : active && playing ? "❚❚" : "▶";

  // karaoke split by char-weight, matching the real player
  const wordsArr = snippet.split(/\s+/).filter(Boolean);
  const lens = wordsArr.map((w) => w.length);
  const totalW = lens.reduce((a, b) => a + b, 0);
  const target = duration > 0 ? (t / duration) * totalW : 0;
  let spoken = 0, acc = 0;
  for (const l of lens) { acc += l; if (acc <= target) spoken++; else break; }
  const spokenText = wordsArr.slice(0, spoken).join(" ");
  const restText = wordsArr.slice(spoken).join(" ");

  return (
    <article
      style={{
        background: active ? "var(--panel)" : "var(--bg)",
        boxShadow: active ? "var(--rail-accent)" : "none",
        border: "1px solid var(--line)",
        borderRadius: "var(--radius)",
        padding: "20px 22px",
        fontFamily: "var(--font-mono)",
        transition: "background var(--dur-base) var(--ease-out)",
        ...style,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
        <button
          onClick={onPlay}
          aria-label={playing ? "Pause" : "Play"}
          style={{
            width: "var(--control-h)", height: "var(--control-h)", flexShrink: 0,
            background: active && playing ? "var(--accent)" : "none",
            color: active && playing ? "var(--bg)" : "var(--accent)",
            border: "1px solid var(--accent)", borderRadius: "var(--radius)",
            fontSize: "var(--text-body)", cursor: "pointer",
            transition: "background var(--dur-fast), transform var(--dur-press) var(--ease-out)",
          }}
          onMouseDown={(e) => (e.currentTarget.style.transform = "scale(0.95)")}
          onMouseUp={(e) => (e.currentTarget.style.transform = "none")}
          onMouseLeave={(e) => (e.currentTarget.style.transform = "none")}
        >
          {playIcon}
        </button>

        <div style={{ flex: 1, minWidth: 0 }}>
          <h3 style={{ fontSize: "var(--text-body)", fontWeight: 600, lineHeight: 1.4, color: "var(--text)", overflowWrap: "anywhere" }}>
            {title}
          </h3>

          <div style={{ color: "var(--dim)", fontSize: "var(--text-sm)", marginTop: 5, display: "flex", flexWrap: "wrap", gap: "4px 10px" }}>
            <span>{date}</span>
            <span>· {fmt(duration)}</span>
            <span>· <Badge variant="text" color={isSummary ? "accent" : "dim"}>{mode}</Badge></span>
            <span>· {voice}</span>
            {words ? <span>· {words} words</span> : null}
          </div>

          {active && isSummary ? (
            <p style={{ fontSize: "var(--text-base)", marginTop: 10, lineHeight: 1.75, color: "var(--dim)", overflowWrap: "anywhere" }}>
              <span style={{ color: "var(--accent)" }}>{spokenText}</span>
              {spokenText && restText ? " " : ""}
              {restText}
            </p>
          ) : snippet ? (
            <p style={{
              color: "var(--dim)", fontSize: "var(--text-base)", marginTop: 10, whiteSpace: "pre-wrap", overflowWrap: "anywhere",
              display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden",
            }}>
              {snippet}
            </p>
          ) : null}

          {active && (
            <div style={{ paddingTop: 14 }}>
              <SeekBar
                elapsed={t}
                duration={duration}
                onSeek={(f) => setT(Math.max(0, Math.min(1, f)) * duration)}
                onSkip={(d) => setT((p) => Math.max(0, Math.min(duration, p + d)))}
              />
            </div>
          )}

          <div style={{ display: "flex", gap: 16, marginTop: 12, fontSize: "var(--text-sm)" }}>
            <a href={sourceUrl} target="_blank" rel="noopener" style={{ color: "var(--accent)" }}>read original ↗</a>
            <button style={{ background: "none", border: "none", color: "var(--dim)", padding: 0, cursor: "pointer", fontFamily: "inherit", fontSize: "var(--text-sm)" }}>delete</button>
          </div>
        </div>
      </div>
    </article>
  );
}
