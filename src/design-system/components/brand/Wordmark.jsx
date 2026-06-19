import React from "react";

/**
 * readback Wordmark — the brand image with an optional subtitle line.
 * Two variants:
 *  - default: the PNG wordmark (src required)
 *  - ascii: the half-block text banner from Header.tsx (self-contained)
 */
export function Wordmark({
  variant = "image", // "image" | "ascii"
  height = 32,
  src,
  subtitle,
  style = {},
}) {
  if (variant === "ascii") {
    return (
      <div style={{ fontFamily: "var(--font-mono)", lineHeight: 1.0, ...style }}>
        <pre style={{ fontSize: height * 0.28, color: "var(--text)", margin: 0, letterSpacing: "0.05em" }}>
          {"▐█▀▀  █▀▀  █▀█  █▀▄  █▀▄  █▀█  █▀▀  █▄▀\n"}
          {"▐█▀▄  ██▄  █▀█  █▄▀  █▀▄  █▀█  █▄▄  █ █"}
        </pre>
        {subtitle && (
          <p style={{ fontFamily: "var(--font-display)", fontWeight: 500, fontSize: "var(--text-base)", color: "var(--dim)", marginTop: 6 }}>
            {subtitle}
          </p>
        )}
      </div>
    );
  }

  return (
    <div style={style}>
      <img
        src={src}
        alt="readback"
        height={height}
        style={{ display: "block", height, width: "auto", imageRendering: "pixelated" }}
      />
      {subtitle && (
        <p style={{ fontFamily: "var(--font-display)", fontWeight: 500, fontSize: "var(--text-base)", color: "var(--dim)", marginTop: 6 }}>
          {subtitle}
        </p>
      )}
    </div>
  );
}
