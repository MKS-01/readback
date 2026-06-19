import React from "react";

/**
 * readback Badge — a low-chrome status tag. Two looks:
 *  - tone="text"  → bare colored inline text (e.g. `· summary` in accent)
 *  - tone="chip"  → a hairline-bordered pill with a faint tinted fill
 * Colors map to the system's semantic palette.
 */
const TONE_COLOR = {
  accent: "var(--accent)",
  green: "var(--green)",
  yellow: "var(--yellow)",
  red: "var(--red)",
  dim: "var(--dim)",
};
const TONE_FILL = {
  accent: "var(--accent-08)",
  green: "var(--green-10)",
  yellow: "var(--yellow-10)",
  red: "var(--red-10)",
  dim: "transparent",
};

export function Badge({
  children,
  color = "accent", // accent | green | yellow | red | dim
  variant = "chip", // "chip" | "text"
  style = {},
}) {
  if (variant === "text") {
    return (
      <span
        style={{
          color: TONE_COLOR[color],
          fontFamily: "var(--font-mono)",
          fontSize: "var(--text-sm)",
          ...style,
        }}
      >
        {children}
      </span>
    );
  }
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "2px 9px",
        fontFamily: "var(--font-mono)",
        fontSize: "var(--text-xs)",
        lineHeight: "var(--leading-normal)",
        color: TONE_COLOR[color],
        background: TONE_FILL[color],
        border: `1px solid ${color === "dim" ? "var(--line)" : TONE_COLOR[color]}`,
        borderRadius: "var(--radius-sm)",
        ...style,
      }}
    >
      {children}
    </span>
  );
}
