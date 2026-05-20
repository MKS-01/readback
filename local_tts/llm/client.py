import logging
import re
import threading
from typing import Iterator, Optional, TYPE_CHECKING

import ollama

from local_tts.config import OllamaConfig, Persona, PersonaConfig

if TYPE_CHECKING:
    from local_tts.tools.registry import ToolRegistry

log = logging.getLogger("local_tts.llm")

# Cap how many tool→model→tool round-trips we'll do before forcing a final
# response. Prevents runaway loops on misbehaving models.
_MAX_TOOL_HOPS = 3

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
    def __init__(
        self,
        cfg: OllamaConfig,
        personas: PersonaConfig,
        tools: Optional["ToolRegistry"] = None,
    ):
        self.cfg = cfg
        self.personas = personas
        self.tools = tools
        self._client = ollama.Client(host=cfg.host)
        # Serializes persona swaps. Reads of `personas.active` in `stream_tokens`
        # are a single atomic attribute access and don't need it; the lock is
        # only to keep `swap_persona` / `set_custom_prompt` write paths consistent.
        self._swap_lock = threading.Lock()

    @property
    def active_persona(self) -> Persona:
        """The currently selected persona. Falls back to the first persona in
        the list if `active` references something missing — defensive against
        config edits or migrations that leave a dangling name."""
        active_name = self.personas.active
        for p in self.personas.personas:
            if p.name == active_name:
                return p
        return self.personas.personas[0]

    def list_personas(self) -> list[str]:
        return [p.name for p in self.personas.personas]

    def swap_persona(self, name: str) -> str:
        """Switch the active persona. Returns the name that was activated.
        In-flight `stream_tokens` calls finish on their original prompt (the
        active name is read once at the top of the function); the next call
        picks up the new persona. Mirrors `Transcriber.swap_model`."""
        with self._swap_lock:
            for p in self.personas.personas:
                if p.name == name:
                    self.personas.active = name
                    return name
            raise ValueError(f"Unknown persona {name!r}")

    def set_custom_prompt(self, prompt: str) -> str:
        """Create or update a persona named 'custom' with the given prompt and
        make it active. Used by the settings panel's free-text persona editor."""
        with self._swap_lock:
            for p in self.personas.personas:
                if p.name == "custom":
                    p.system_prompt = prompt
                    self.personas.active = "custom"
                    return "custom"
            self.personas.personas.append(Persona(name="custom", system_prompt=prompt))
            self.personas.active = "custom"
            return "custom"

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
        # Snapshot the persona once at the start so a mid-stream swap doesn't
        # mix prompts within a single response.
        system_prompt = self.active_persona.system_prompt
        messages = [{"role": "system", "content": system_prompt}] + history
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
        """Yield complete sentences as they're produced.

        When `self.tools` is wired AND `tools.enabled`, intercepts tool_calls
        from Ollama, runs them, and continues the chat with the result. Tool
        round-trip content stays out of the TTS stream — only the final
        post-tool response is sentence-split for speech."""
        if self.tools is not None and self.tools.enabled:
            yield from stream_sentences(
                self._stream_tokens_with_tools(history, stop_event)
            )
        else:
            yield from stream_sentences(self.stream_tokens(history, stop_event))

    def _stream_tokens_with_tools(
        self,
        history: list[dict],
        stop_event: Optional[threading.Event],
    ) -> Iterator[str]:
        """Tools path: non-streaming probe for tool_calls, run them, then
        stream the final response. We deliberately don't stream during a
        tool-call hop — the partial content is usually just a planning
        preamble that would speak awkwardly before the actual answer."""
        assert self.tools is not None
        system_prompt = self.active_persona.system_prompt
        cur_history = list(history)
        tool_schemas = self.tools.schemas_for_active()

        for hop in range(_MAX_TOOL_HOPS):
            if stop_event is not None and stop_event.is_set():
                return
            if not tool_schemas:
                break
            try:
                response = self._client.chat(
                    model=self.cfg.model,
                    messages=(
                        [{"role": "system", "content": system_prompt}] + cur_history
                    ),
                    tools=tool_schemas,
                    stream=False,
                    options={"temperature": 0.7},
                )
            except Exception as e:
                yield f"Sorry, I hit an error talking to Ollama: {e}"
                return

            msg = response.message
            tool_calls = list(msg.tool_calls or [])
            if not tool_calls:
                # Model decided no tools were needed — surface its content as
                # one big chunk to the sentence splitter.
                content = msg.content or ""
                if content:
                    yield _strip_markdown(content)
                return

            # Append the assistant turn that *requested* the tools, then run
            # each tool and append its result. Ollama expects this exact shape.
            cur_history.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                args = tc.function.arguments or {}
                if isinstance(args, str):
                    # Some models emit JSON-stringified arguments; normalize.
                    import json as _json
                    try:
                        args = _json.loads(args)
                    except Exception:
                        args = {}
                result = self.tools.run(tc.function.name, args)
                log.info("tool_call: %s -> %d chars", tc.function.name, len(result))
                cur_history.append({
                    "role": "tool",
                    "name": tc.function.name,
                    "content": result,
                })

        # Either we hit the hop cap or there were no tools — stream a final
        # response on the (possibly tool-augmented) history. No tools this round
        # so the model is forced to actually answer.
        if stop_event is not None and stop_event.is_set():
            return
        messages = [{"role": "system", "content": system_prompt}] + cur_history
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
