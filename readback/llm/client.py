"""Ollama client for the reader's Summary mode.

The reader uses a single non-streaming completion (`oneshot`) to turn an article
into a spoken-style explanation. The streaming / tool-calling machinery from the
old voice-assistant era is gone — this module is just the one call plus the
`<think>` stripper that keeps reasoning out of the spoken text.
"""
import logging

import ollama

from readback.config import OllamaConfig

log = logging.getLogger("readback.llm")


_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def _safe_emit_len(buf: str, needles: tuple[str, ...]) -> int:
    """Length of `buf` safe to emit now — i.e. excluding any trailing suffix
    that could be the start of one of `needles` once more tokens arrive."""
    keep = 0
    for n in needles:
        for k in range(min(len(buf), len(n) - 1), 0, -1):
            if buf[-k:] == n[:k]:
                keep = max(keep, k)
                break
    return len(buf) - keep


class _ThinkStripper:
    """Removes `<think>…</think>` spans from model output.

    We set `think=False` on the Ollama call so reasoning normally lands in
    `message.thinking`, never `content`. This is the belt-and-suspenders guard
    for GGUF builds that still emit inline `<think>` tags in `content`."""

    def __init__(self):
        self._in_think = False
        self._buf = ""

    def feed(self, text: str) -> str:
        self._buf += text
        out: list[str] = []
        while self._buf:
            if not self._in_think:
                i = self._buf.find(_THINK_OPEN)
                if i != -1:
                    out.append(self._buf[:i])
                    self._buf = self._buf[i + len(_THINK_OPEN):]
                    self._in_think = True
                    continue
                cut = _safe_emit_len(self._buf, (_THINK_OPEN,))
                out.append(self._buf[:cut])
                self._buf = self._buf[cut:]
                break
            else:
                i = self._buf.find(_THINK_CLOSE)
                if i != -1:
                    self._buf = self._buf[i + len(_THINK_CLOSE):]
                    self._in_think = False
                    continue
                cut = _safe_emit_len(self._buf, (_THINK_CLOSE,))
                self._buf = self._buf[cut:]
                break
        return "".join(out)

    def flush(self) -> str:
        """Emit any trailing buffered text at stream end. Anything still inside
        an unclosed `<think>` is discarded."""
        tail = "" if self._in_think else self._buf
        self._buf = ""
        return tail


def strip_think(text: str) -> str:
    """One-shot `<think>…</think>` removal."""
    s = _ThinkStripper()
    return s.feed(text) + s.flush()


class LLMClient:
    def __init__(self, cfg: OllamaConfig):
        self.cfg = cfg
        self._client = ollama.Client(host=cfg.host)

    def oneshot(self, system_prompt: str, user_text: str) -> str:
        """Single non-streaming completion with an explicit system prompt. Used by
        the reader's Summary mode. Returns clean text (think tags stripped)."""
        try:
            response = self._client.chat(
                model=self.cfg.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                stream=False,
                think=False,
                options={"temperature": 0.4},
            )
            return strip_think(response.message.content or "").strip()
        except Exception as e:
            log.exception("oneshot completion failed")
            return f"Sorry, I hit an error talking to Ollama: {e}"
