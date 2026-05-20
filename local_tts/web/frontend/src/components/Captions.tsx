// User + AI captions section. Replaces the manual DOM append loop in
// legacy app.js (appendAiSentence + showUserCaption). The INPUT label
// animates per-phase: LISTENING_ (caret blink) / PROCESSING ··· (dots).

import { useEffect, useRef, useState } from "react";
import { useAppStore } from "../state/store";
import { CopyIcon } from "./icons";

const USER_CAPTION_FADE_MS = 6000;

export function Captions() {
  const phase = useAppStore((s) => s.phase);
  const userCaption = useAppStore((s) => s.userCaption);
  const aiSentences = useAppStore((s) => s.aiSentences);
  const aiAccum = useAppStore((s) => s.aiAccum);
  const setUserCaption = useAppStore((s) => s.setUserCaption);
  const inputMode = useAppStore((s) => s.inputMode);
  const wakewordModel = useAppStore((s) => s.wakewordModel);

  const [copied, setCopied] = useState(false);
  const aiBoxRef = useRef<HTMLDivElement | null>(null);
  const userCaptionTimer = useRef<number | null>(null);

  // Fade the user caption so it doesn't compete with the streamed AI response.
  useEffect(() => {
    if (!userCaption) return;
    if (userCaptionTimer.current) window.clearTimeout(userCaptionTimer.current);
    userCaptionTimer.current = window.setTimeout(() => {
      setUserCaption("");
    }, USER_CAPTION_FADE_MS);
    return () => {
      if (userCaptionTimer.current)
        window.clearTimeout(userCaptionTimer.current);
    };
  }, [userCaption, setUserCaption]);

  // Auto-scroll AI captions as new sentences arrive.
  useEffect(() => {
    if (aiBoxRef.current) {
      aiBoxRef.current.scrollTop = aiBoxRef.current.scrollHeight;
    }
  }, [aiSentences.length]);

  // Reset "Copied" indicator on response change.
  useEffect(() => {
    setCopied(false);
  }, [aiSentences.length]);

  // Dynamic INPUT label class/text.
  let inputLabelClass = "caption-label";
  let inputLabelText: string = "Input";
  if (phase === "listening") {
    inputLabelClass += " is-listening";
    inputLabelText = "Listening";
  } else if (phase === "thinking") {
    inputLabelClass += " is-thinking";
    inputLabelText = "Processing";
  }

  const onCopy = async () => {
    if (!aiAccum) return;
    try {
      await navigator.clipboard.writeText(aiAccum);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      /* swallow — UI just won't flash */
    }
  };

  const hasAi = aiSentences.length > 0;
  const hasContent = hasAi || !!userCaption;

  // Empty-state hint surfaced inside the input slot until the user takes a
  // turn. Tells them how to start a call in their current listening mode.
  const emptyHint =
    inputMode === "wake_word"
      ? `Say "${(wakewordModel || "hey jarvis").replace(/_/g, " ")}" or tap Type to start`
      : "Tap mic to speak, or hit Type to send a message";

  return (
    <div id="captions" className="captions">
      <div className="caption-frame">
        <span id="input-label" className={inputLabelClass}>
          {inputLabelText}
        </span>
        <div
          id="user-caption"
          className={`caption user ${userCaption || !hasContent ? "show" : ""}`}
          style={!userCaption && !hasContent ? { opacity: 0.4 } : undefined}
        >
          {userCaption || (!hasContent ? emptyHint : "")}
        </div>
      </div>
      <div className="caption-frame ai-frame">
        <span className="caption-label">Response</span>
        <div
          id="ai-caption"
          ref={aiBoxRef}
          className={`caption ai ${hasAi ? "show" : ""}`}
        >
          {aiSentences.map((line, i) => (
            <div key={i} className="ai-sentence">
              {line}
            </div>
          ))}
        </div>
        {hasAi ? (
          <button
            id="copy-btn"
            className={`copy-btn ${copied ? "copied" : ""}`}
            type="button"
            aria-label="Copy response"
            title="Copy response"
            onClick={onCopy}
          >
            <CopyIcon />
            <span className="copy-label">{copied ? "Copied" : "Copy"}</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}
