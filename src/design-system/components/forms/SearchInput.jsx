import React, { useState } from "react";

/**
 * readback SearchInput — a panel-filled field with a leading accent sigil.
 * Border turns accent on focus. Mirrors the dashboard's library search.
 */
export function SearchInput({
  value,
  onChange,
  placeholder = "search title, summary, url…",
  sigil = "/",
  style = {},
}) {
  const [focus, setFocus] = useState(false);
  return (
    <div
      style={{
        flex: 1,
        minWidth: 200,
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "9px 14px",
        background: "var(--panel)",
        border: `1px solid ${focus ? "var(--accent)" : "var(--line)"}`,
        borderRadius: "var(--radius)",
        transition: "border-color var(--dur-fast)",
        ...style,
      }}
    >
      <span style={{ color: "var(--accent)", fontSize: "var(--text-base)", fontFamily: "var(--font-mono)" }}>
        {sigil}
      </span>
      <input
        value={value}
        onChange={(e) => onChange && onChange(e.target.value)}
        onFocus={() => setFocus(true)}
        onBlur={() => setFocus(false)}
        placeholder={placeholder}
        style={{
          flex: 1,
          background: "none",
          border: "none",
          outline: "none",
          color: "var(--text)",
          fontFamily: "var(--font-mono)",
          fontSize: "var(--text-body)",
        }}
      />
    </div>
  );
}
