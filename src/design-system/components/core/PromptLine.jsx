import React from "react";

/**
 * readback PromptLine — the signature terminal prompt with a blinking caret.
 * Used as a kicker above headers and in footers: `~ $ readback-cli --library▮`
 */
export function PromptLine({
  cwd = "~",
  command,
  caret = true,
  style = {},
}) {
  return (
    <p
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: "var(--text-base)",
        color: "var(--dim)",
        display: "flex",
        alignItems: "center",
        flexWrap: "wrap",
        ...style,
      }}
    >
      <span>{cwd} $</span>
      {command ? <span>&nbsp;{command}</span> : null}
      {caret ? <Caret /> : null}
    </p>
  );
}

/** The blinking accent caret on its own — a 9×3px block. */
export function Caret({ style = {} }) {
  return (
    <span
      aria-hidden="true"
      style={{
        display: "inline-block",
        width: 9,
        height: 3,
        marginLeft: 7,
        background: "var(--accent)",
        animation: "rb-blink 1.1s steps(1) infinite",
        ...style,
      }}
    />
  );
}
