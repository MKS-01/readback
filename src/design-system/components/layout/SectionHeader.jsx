import React from "react";

/**
 * readback SectionHeader — a section heading with a hairline bottom border.
 * Matches the landing page h2 style: Martian Mono, --text-lg, 700.
 */
export function SectionHeader({ children, style = {} }) {
  return (
    <h2
      style={{
        fontFamily: "var(--font-display)",
        fontSize: "var(--text-lg)",
        fontWeight: 700,
        letterSpacing: "0.03em",
        paddingBottom: 14,
        marginBottom: 24,
        borderBottom: "1px solid var(--line)",
        color: "var(--text)",
        ...style,
      }}
    >
      {children}
    </h2>
  );
}
