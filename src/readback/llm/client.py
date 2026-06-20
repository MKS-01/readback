"""MLX-LM client for the reader's Summary mode.

The reader uses a single non-streaming completion (`oneshot`) to turn an article
into a spoken-style explanation. The model + tokenizer are loaded lazily on first
call via mlx-lm, running in-process on Apple Silicon (same MLX framework as
CSM-1B TTS). The `<think>` stripper keeps reasoning tokens out of the spoken text.
"""
import logging

from readback.config import LLMConfig

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

    Qwen3.5 models may still emit inline `<think>` tags even without explicit
    thinking-mode activation. This is the belt-and-suspenders guard."""

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
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._model = None
        self._tokenizer = None
        self._loaded_model_id: str | None = None

    def _ensure_loaded(self):
        if self._model is not None and self._loaded_model_id == self.cfg.model:
            return
        from mlx_lm import load
        if self._model is not None:
            log.info("unloading %s", self._loaded_model_id)
            del self._model, self._tokenizer
            self._model = None
            self._tokenizer = None
        log.info("loading LLM %s", self.cfg.model)
        self._model, self._tokenizer = load(self.cfg.model)
        self._loaded_model_id = self.cfg.model
        log.info("LLM ready: %s", self.cfg.model)

    def oneshot(self, system_prompt: str, user_text: str) -> str:
        """Single non-streaming completion with an explicit system prompt. Used by
        the reader's Summary mode. Returns clean text (think tags stripped)."""
        try:
            from mlx_lm import generate

            self._ensure_loaded()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ]
            prompt = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
            )
            result = generate(
                self._model, self._tokenizer, prompt=prompt,
                max_tokens=4096, temperature=0.4, verbose=False,
            )
            return strip_think(result or "").strip()
        except Exception as e:
            log.exception("oneshot completion failed")
            return f"Sorry, I hit an error running the LLM: {e}"
