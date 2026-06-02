// Pill-shaped text input that slides up from the dock. Submitting bypasses
// STT and goes straight to the LLM pipeline (the server's `text_input`
// message). Outside-click closes the popover.

import { useEffect, useRef, useState } from "react";

interface TypePopoverProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (text: string) => void;
}

export function TypePopover({ open, onClose, onSubmit }: TypePopoverProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const formRef = useRef<HTMLFormElement | null>(null);
  const [value, setValue] = useState("");

  useEffect(() => {
    if (!open) return;
    // Wait a frame so the unhide finishes before focusing.
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [open]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!formRef.current) return;
      const target = e.target as Node;
      if (formRef.current.contains(target)) return;
      // Exempt the type button itself — it has its own toggle handler.
      const typeBtn = document.getElementById("type-btn");
      if (typeBtn && typeBtn.contains(target)) return;
      onClose();
    };
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, [open, onClose]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = value.trim();
    if (!text) return;
    onSubmit(text);
    setValue("");
    onClose();
  };

  return (
    <form
      ref={formRef}
      id="text-input-form"
      className="text-input-popover"
      autoComplete="off"
      hidden={!open}
      onSubmit={submit}
    >
      <input
        ref={inputRef}
        id="text-input"
        className="text-input"
        type="text"
        placeholder="Type a message…"
        aria-label="Type a message"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
      />
      <button type="submit" className="text-send" aria-label="Send">
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <line x1="22" y1="2" x2="11" y2="13" />
          <polygon points="22 2 15 22 11 13 2 9 22 2" />
        </svg>
      </button>
    </form>
  );
}
