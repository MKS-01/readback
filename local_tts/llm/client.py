import re
from typing import Iterator

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

    def stream_tokens(self, history: list[dict]) -> Iterator[str]:
        """Yield raw text tokens from Ollama. History should include system + turns."""
        messages = [{"role": "system", "content": self.cfg.system_prompt}] + history
        try:
            response = self._client.chat(
                model=self.cfg.model,
                messages=messages,
                stream=True,
                options={"temperature": 0.7},
            )
            for chunk in response:
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield _strip_markdown(content)
        except Exception as e:
            yield f"Sorry, I hit an error talking to Ollama: {e}"

    def stream_response(self, history: list[dict]) -> Iterator[str]:
        """Yield complete sentences as they're produced."""
        yield from stream_sentences(self.stream_tokens(history))

    def list_models(self) -> list[str]:
        try:
            resp = self._client.list()
            return [m.get("model", m.get("name", "")) for m in resp.get("models", [])]
        except Exception:
            return []
