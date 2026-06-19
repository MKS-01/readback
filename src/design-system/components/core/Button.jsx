import React, { useState } from "react";

/**
 * readback Button — terminal-ghost by default, faint accent fill for primary.
 * No bounce: hover lifts 1px (ghost) or brightens (accent); press shrinks to 0.97.
 */
export function Button({
  children,
  variant = "ghost", // "ghost" | "accent"
  size = "md",       // "sm" | "md"
  href,
  disabled = false,
  onClick,
  style = {},
  ...rest
}) {
  const [hover, setHover] = useState(false);
  const [press, setPress] = useState(false);

  const pad = size === "sm" ? "7px 14px" : "10px 22px";
  const fontSize = size === "sm" ? "var(--text-base)" : "var(--text-body)";

  const base = {
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    padding: pad,
    fontFamily: "var(--font-mono)",
    fontSize,
    lineHeight: 1.2,
    border: "1px solid var(--line)",
    borderRadius: "var(--radius)",
    color: "var(--text)",
    background: "none",
    cursor: disabled ? "default" : "pointer",
    opacity: disabled ? 0.5 : 1,
    textDecoration: "none",
    transition:
      "border-color var(--dur-fast), color var(--dur-fast), background var(--dur-fast), transform var(--dur-press) var(--ease-out)",
    transform: press ? "scale(0.97)" : hover && !disabled ? "translateY(-1px)" : "none",
  };

  const variants = {
    ghost: {
      borderColor: hover && !disabled ? "var(--dim)" : "var(--line)",
    },
    accent: {
      borderColor: hover && !disabled ? "var(--accent-hi)" : "var(--accent)",
      color: hover && !disabled ? "var(--accent-hi)" : "var(--accent)",
      background: hover && !disabled ? "var(--accent-14)" : "var(--accent-08)",
      transform: press ? "scale(0.97)" : "none", // accent doesn't lift
    },
  };

  const styles = { ...base, ...variants[variant], ...style };
  const handlers = {
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => { setHover(false); setPress(false); },
    onMouseDown: () => !disabled && setPress(true),
    onMouseUp: () => setPress(false),
    onClick: disabled ? undefined : onClick,
  };

  if (href && !disabled) {
    return (
      <a href={href} style={styles} {...handlers} {...rest}>
        {children}
      </a>
    );
  }
  return (
    <button type="button" disabled={disabled} style={styles} {...handlers} {...rest}>
      {children}
    </button>
  );
}
