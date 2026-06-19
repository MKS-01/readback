import React, { useState, useRef, useEffect } from "react";

/**
 * readback WaveformPlayer — the landing-page sample player. A framed play
 * control beside a floating waveform; played bars light accent and sway while
 * running. Self-driving demo clock when no real audio is wired.
 */
function fmt(s) {
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

export function WaveformPlayer({ bars = 52, duration = 111, style = {} }) {
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
      setT((prev) => {
        const next = prev + dt;
        if (next >= duration) { setPlaying(false); return duration; }
        return next;
      });
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf.current); last.current = null; };
  }, [playing, duration]);

  const frac = duration ? t / duration : 0;
  const lit = Math.floor(frac * bars);

  const heights = Array.from({ length: bars }, (_, i) => {
    const h = 22 + 70 * Math.abs(Math.sin(i * 7.31) * 0.6 + Math.sin(i * 1.7) * 0.4);
    return Math.min(h, 95);
  });

  const seek = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    setT(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * duration);
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 18, padding: "6px 0", ...style }}>
      <button
        onClick={() => { if (t >= duration) setT(0); setPlaying((p) => !p); }}
        aria-label={playing ? "Pause" : "Play"}
        style={{
          width: "var(--control-h)", height: "var(--control-h)", flexShrink: 0,
          background: "none", border: "1px solid var(--accent)", color: "var(--accent)",
          borderRadius: "var(--radius)", fontSize: "var(--text-base)", cursor: "pointer",
          transition: "background var(--dur-fast), transform var(--dur-press) var(--ease-out)",
        }}
        onMouseDown={(e) => (e.currentTarget.style.transform = "scale(0.95)")}
        onMouseUp={(e) => (e.currentTarget.style.transform = "none")}
        onMouseLeave={(e) => (e.currentTarget.style.transform = "none")}
      >
        {playing ? "❚❚" : "▶"}
      </button>

      <div
        onClick={seek}
        style={{ flex: 1, display: "flex", alignItems: "center", gap: 3, height: 38, cursor: "pointer" }}
      >
        {heights.map((h, i) => {
          const on = i < lit;
          return (
            <i
              key={i}
              style={{
                flex: 1, height: `${h}%`,
                background: on ? "var(--accent)" : "var(--line)",
                transition: "background var(--dur-base) var(--ease-out)",
                transformOrigin: "center",
                animation: playing && on ? "rb-sway 0.9s ease-in-out infinite alternate" : "none",
                animationDelay: `${(i % 7) * 0.11}s`,
              }}
            />
          );
        })}
      </div>

      <span style={{ color: "var(--dim)", fontSize: "var(--text-base)", minWidth: 86, textAlign: "right", flexShrink: 0, fontFamily: "var(--font-mono)" }}>
        {fmt(t)} / {fmt(duration)}
      </span>

      <style>{`@keyframes rb-sway { to { transform: scaleY(0.45); } }`}</style>
    </div>
  );
}
