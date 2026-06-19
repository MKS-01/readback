import React from "react";

/**
 * readback SeekBar — the dashboard/CLI track player: time · thin seek rail with
 * accent fill + knob · time · ±5s skip buttons. Controlled via elapsed/duration.
 */
function fmt(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function Skip({ children, onClick, label }) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      style={{
        background: "none", border: "1px solid var(--line)", borderRadius: 6,
        color: "var(--dim)", fontSize: "var(--text-xs)", padding: "3px 8px", cursor: "pointer",
        fontFamily: "var(--font-mono)",
        transition: "border-color var(--dur-fast), color var(--dur-fast), transform var(--dur-press) var(--ease-out)",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.color = "var(--accent)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--line)"; e.currentTarget.style.color = "var(--dim)"; e.currentTarget.style.transform = "none"; }}
      onMouseDown={(e) => (e.currentTarget.style.transform = "scale(0.95)")}
      onMouseUp={(e) => (e.currentTarget.style.transform = "none")}
    >
      {children}
    </button>
  );
}

export function SeekBar({
  elapsed = 0,
  duration = 0,
  onSeek,
  onSkip,
  skips = true,
  style = {},
}) {
  const frac = duration > 0 ? Math.min(elapsed / duration, 1) : 0;
  const seek = (e) => {
    if (!onSeek) return;
    const r = e.currentTarget.getBoundingClientRect();
    onSeek((e.clientX - r.left) / r.width);
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, ...style }}>
      <span style={{ fontSize: "var(--text-sm)", color: "var(--text)", minWidth: 34, flexShrink: 0, fontFamily: "var(--font-mono)" }}>
        {fmt(elapsed)}
      </span>

      <div
        onClick={seek}
        role="slider"
        aria-label="Seek"
        style={{ flex: 1, height: 14, display: "flex", alignItems: "center", cursor: "pointer", position: "relative" }}
      >
        <span style={{ position: "absolute", width: "100%", height: 3, background: "var(--line)" }} />
        <span style={{ position: "relative", height: 3, background: "var(--accent)", width: `${frac * 100}%`, minWidth: 1 }}>
          <span style={{ position: "absolute", right: -4, top: "50%", width: 8, height: 8, transform: "translateY(-50%)", background: "var(--accent)", borderRadius: "50%" }} />
        </span>
      </div>

      <span style={{ fontSize: "var(--text-sm)", color: "var(--dim)", minWidth: 34, textAlign: "right", flexShrink: 0, fontFamily: "var(--font-mono)" }}>
        {fmt(duration)}
      </span>

      {skips && (
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <Skip label="Back 5 seconds" onClick={() => onSkip && onSkip(-5)}>« 5s</Skip>
          <Skip label="Forward 5 seconds" onClick={() => onSkip && onSkip(5)}>5s »</Skip>
        </div>
      )}
    </div>
  );
}
