import re
import threading
from typing import Iterator, Optional

import ollama

from local_tts.config import OllamaConfig

# Sentence boundary: punctuation followed by whitespace OR end of string
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_MIN_SENTENCE_LEN = 8


def stream_sentences(token_iter: Iterator[str]) -> Iterator[str]:
    """Buffer streaming tokens and yield complete sentences as they form."""
    buffer = ""
    for token in token_iter:
        buffer += token
        # Split on sentence boundaries
        parts = _SENTENCE_BOUNDARY.split(buffer)
        while len(parts) > 1:
            sentence = parts.pop(0).strip()
            if len(sentence) >= _MIN_SENTENCE_LEN:
                yield sentence
            else:
                # Too short — stitch back to the next part so we don't lose it
                if parts:
                    parts[0] = sentence + " " + parts[0]
            buffer = parts[0] if parts else ""
    tail = buffer.strip()
    if tail:
        yield tail


def _strip_markdown(text: str) -> str:
    """Quick scrub of common markdown so TTS doesn't read it literally."""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^[>#\-\*]+\s*", "", text, flags=re.MULTILINE)
    return text


class LLMClient:
    def __init__(self, cfg: OllamaConfig):
        self.cfg = cfg
        self._client = ollama.Client(host=cfg.host)

    def stream_tokens(
        self,
        history: list[dict],
        stop_event: Optional[threading.Event] = None,
    ) -> Iterator[str]:
        """Yield raw text tokens from Ollama. History should include system + turns.

        If `stop_event` is provided and gets set mid-stream, the generator
        breaks early and closes the underlying HTTP stream — used by the web
        server's interrupt path so we don't keep burning tokens after Skip.
        """
        messages = [{"role": "system", "content": self.cfg.system_prompt}] + history
        try:
            response = self._client.chat(
                model=self.cfg.model,
                messages=messages,
                stream=True,
                options={"temperature": 0.7},
            )
            for chunk in response:
                if stop_event is not None and stop_event.is_set():
                    break
                content = chunk.message.content or ""
                if content:
                    yield _strip_markdown(content)
        except Exception as e:
            yield f"Sorry, I hit an error talking to Ollama: {e}"

    def stream_response(
        self,
        history: list[dict],
        stop_event: Optional[threading.Event] = None,
    ) -> Iterator[str]:
        """Yield complete sentences as they're produced."""
        yield from stream_sentences(self.stream_tokens(history, stop_event))

    def unload_model(self, name: str) -> None:
        """Evict a model from Ollama's unified memory (keep_alive=0)."""
        try:
            self._client.generate(model=name, prompt="", keep_alive=0)
        except Exception:
            pass

    def list_models(self) -> list[str]:
        try:
            resp = self._client.list()
            return [m.model for m in resp.models if m.model]
        except Exception:
            return []
