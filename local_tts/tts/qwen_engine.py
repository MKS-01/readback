import concurrent.futures
import queue
from collections.abc import Iterator
from pathlib import Path
from typing import Callable, Optional, TypeVar

import numpy as np

from local_tts.config import CloneVoiceConfig, QwenTTSConfig

# Qwen3-TTS CustomVoice preset speakers (from model.get_supported_speakers()).
# (id, label) pairs exposed to the web UI's voice picker.
SUPPORTED_VOICES: tuple[tuple[str, str], ...] = (
    ("ryan",      "Ryan — male ★"),
    ("eric",      "Eric — male"),
    ("aiden",     "Aiden — male"),
    ("dylan",     "Dylan — male"),
    ("uncle_fu",  "Uncle Fu — male"),
    ("serena",    "Serena — female ★"),
    ("vivian",    "Vivian — female"),
    ("ono_anna",  "Ono Anna — female"),
    ("sohee",     "Sohee — female"),
)
SUPPORTED_VOICE_NAMES: tuple[str, ...] = tuple(v for v, _ in SUPPORTED_VOICES)

# Cloned voices are exposed to the UI as "clone:<name>" so they ride the same
# voice picker / set_voice path as presets, with zero protocol changes. The
# prefix is also how the engine decides which model checkpoint to load.
CLONE_PREFIX = "clone:"

_SAMPLE_RATE = 24000  # Qwen3-TTS native rate — matches the WS Float32 contract.

# With stream=True the qwen3_tts model yields incremental audio every
# ~streaming_interval*12.5 tokens (~12.5 audio tokens/sec). Smaller = lower
# first-audio latency and a more continuously-fed playback queue, at the cost of
# re-decoding a growing window each interval. 0.5s ≈ a chunk every half second.
STREAM_INTERVAL_SEC = 0.5

# Sentinel pushed onto the engine→caller bridge queue when a streamed synth ends.
_STREAM_DONE = object()

# Qwen3-TTS generates ~12 audio tokens/sec. The upstream default max_tokens=4096
# is ~340s of audio — so if the model fails to emit an end token on a sentence
# (more likely on long text / high temperature), one synth call can grind for
# minutes and the whole pipeline looks hung. Cap it proportional to the text with
# generous (~6x) headroom so nothing legitimate is truncated, but runaway
# generation is bounded to a few tens of seconds instead of ~340s.
def _max_tokens_for(text: str) -> int:
    return min(4096, max(512, len(text) * 6))

_T = TypeVar("_T")


def _to_numpy(audio) -> np.ndarray:
    """Coerce an mlx/torch/np audio array to 1-D float32."""
    if audio is None:
        return np.zeros(0, dtype=np.float32)
    if hasattr(audio, "detach"):           # torch tensor
        audio = audio.detach().cpu().numpy()
    arr = np.asarray(audio, dtype=np.float32)
    return arr.reshape(-1)


class QwenEngine:
    """Qwen3-TTS via mlx-audio. Like Parakeet, MLX binds its GPU stream to the
    thread that first touches the device, so ALL model work (load + synth) runs
    on a single owned executor thread; public methods submit and block.

    Two checkpoints, one loaded at a time (chosen by the active voice):
      * preset speakers → CustomVoice model, generate_custom_voice(speaker=...)
      * clones          → Base model, generate(ref_audio=..., ref_text=...)
    Crossing between the two triggers a model reload on the executor thread."""

    name = "qwen"

    def __init__(self, cfg: QwenTTSConfig):
        self.cfg = cfg
        self._model = None
        self._loaded_kind: Optional[str] = None   # "base" | "preset" | None
        # Configured clones, keyed by bare name. ref_text is resolved lazily
        # (Whisper, off this thread) and cached here so synth never blocks on it.
        self._clones: dict[str, CloneVoiceConfig] = {}
        self._ref_text: dict[str, str] = {}
        self.set_clones(cfg.clones)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="qwen-tts",
        )

    def _run(self, fn: Callable[..., _T], *args) -> _T:
        return self._executor.submit(fn, *args).result()

    # ---- clone registry (called from the server thread) ----

    def set_clones(self, clones) -> None:
        """(Re)load the configured clone list. Pre-seeds ref_text for any clone
        that ships an explicit transcript."""
        self._clones = {c.name: c for c in (clones or [])}
        for c in (clones or []):
            if c.ref_text:
                self._ref_text[c.name] = c.ref_text

    def set_ref_text(self, name: str, text: str) -> None:
        """Cache a resolved reference transcript (from Whisper, off the MLX
        thread) so the next synth on this clone can run without blocking."""
        self._ref_text[name] = text

    @staticmethod
    def is_clone(voice: str) -> bool:
        return voice.startswith(CLONE_PREFIX)

    @staticmethod
    def _clone_name(voice: str) -> str:
        return voice[len(CLONE_PREFIX):]

    def clone_for(self, voice: str) -> Optional[CloneVoiceConfig]:
        if not self.is_clone(voice):
            return None
        return self._clones.get(self._clone_name(voice))

    def has_ref_text(self, voice: str) -> bool:
        return bool(self._ref_text.get(self._clone_name(voice)))

    def _kind_for_voice(self, voice: str) -> str:
        return "base" if self.is_clone(voice) else "preset"

    def _model_id_for_kind(self, kind: str) -> str:
        return self.cfg.base_model if kind == "base" else self.cfg.model

    def _ref_for(self, voice: str) -> tuple[Optional[str], Optional[str]]:
        """(expanded wav path, cached ref_text) for a clone voice."""
        c = self._clones.get(self._clone_name(voice))
        if c is None:
            return None, None
        return str(Path(c.wav).expanduser()), self._ref_text.get(c.name)

    def _instruct_for(self, voice: str) -> Optional[str]:
        """Per-clone emotion/style hint, falling back to the global one."""
        c = self._clones.get(self._clone_name(voice))
        if c is not None and c.instruct:
            return c.instruct
        return self.cfg.instruct

    def _gen_kwargs_for(self, voice: str) -> dict:
        """Per-clone speed/temperature overrides for generate(), falling back to
        the engine defaults (cfg.speed; model default temperature when unset)."""
        c = self._clones.get(self._clone_name(voice))
        speed = c.speed if (c is not None and c.speed is not None) else self.cfg.speed
        kwargs = {"speed": speed}
        if c is not None and c.temperature is not None:
            kwargs["temperature"] = c.temperature
        return kwargs

    # ---- public surface ----

    @property
    def sample_rate(self) -> int:
        return _SAMPLE_RATE

    @property
    def current_voice(self) -> str:
        return self.cfg.speaker

    @property
    def supported_voices(self) -> tuple[tuple[str, str], ...]:
        clones = tuple(
            (CLONE_PREFIX + c.name, c.label or c.name) for c in self._clones.values()
        )
        return SUPPORTED_VOICES + clones

    def load(self):
        self._run(self._ensure_kind_impl, self.cfg.speaker)

    def swap_voice(self, voice: str) -> str:
        """Switch the active voice. Preset→preset is instant (just a per-call
        speaker arg). Crossing preset↔clone reloads the model on the executor
        thread. A clone's ref_text must already be cached (server resolves it)."""
        if self.is_clone(voice):
            name = self._clone_name(voice)
            if name not in self._clones:
                raise ValueError(f"Unknown clone {voice!r}")
            if not self._ref_text.get(name):
                raise ValueError(f"Clone {voice!r} has no reference transcript yet")
        elif voice not in SUPPORTED_VOICE_NAMES:
            raise ValueError(
                f"Unsupported speaker {voice!r}; pick from {SUPPORTED_VOICE_NAMES}"
            )
        self._run(self._ensure_kind_impl, voice)
        self.cfg.speaker = voice
        return voice

    def synthesize(self, text: str) -> np.ndarray:
        text = text.strip()
        if not text:
            return np.zeros(0, dtype=np.float32)
        return self._run(self._synthesize_impl, text)

    def synthesize_stream(
        self, text: str, should_stop: Optional[Callable[[], bool]] = None,
    ) -> Iterator[np.ndarray]:
        """Yield this sentence's audio in chunks as the model produces them.

        The model generator runs on the single MLX executor thread (MLX is not
        multi-thread safe); chunks cross to this caller via a bounded queue. The
        caller MUST drain to completion — pass `should_stop` (polled on the
        executor thread) to end generation early instead of breaking the loop, so
        the executor never blocks on a full queue nobody is draining.
        """
        text = text.strip()
        if not text:
            return
        q: "queue.Queue" = queue.Queue(maxsize=8)   # backpressure cap
        fut = self._executor.submit(
            self._synthesize_stream_impl, text, should_stop, q,
        )
        while True:
            item = q.get()
            if item is _STREAM_DONE:
                break
            yield item
        fut.result()   # surface any exception raised on the executor thread

    def reset_context(self):
        # Stateless across calls — nothing to reset.
        pass

    # ---- impls (run ON the MLX executor thread) ----

    def _ensure_kind_impl(self, voice: str):
        """Load (or reload) whichever checkpoint the target voice needs."""
        kind = self._kind_for_voice(voice)
        if self._model is not None and self._loaded_kind == kind:
            return
        self._load_kind_impl(kind, voice)

    def _load_kind_impl(self, kind: str, voice: str):
        from mlx_audio.tts.utils import load_model

        # Free the previous model BEFORE loading the new one so the two don't
        # co-reside in Metal memory during the swap.
        if self._model is not None:
            self._model = None
            self._loaded_kind = None
            try:
                import mlx.core as mx
                mx.clear_cache()
            except Exception:
                pass

        self._model = load_model(self._model_id_for_kind(kind))
        self._loaded_kind = kind
        # Warm the graph so the first real utterance doesn't pay the ~2s
        # cold-start compile cost. Best-effort — never fatal.
        try:
            if kind == "base":
                wav, ref = self._ref_for(voice)
                if wav and ref:
                    for _ in self._model.generate(
                        "Hello.", ref_audio=wav, ref_text=ref, lang_code="auto",
                    ):
                        pass
            else:
                for _ in self._model.generate_custom_voice("Hello.", speaker=voice):
                    pass
        except Exception:
            pass

    def _build_gen(self, text: str, stream: bool):
        """Construct the model generator for the active voice. ON the executor
        thread only. `stream=True` makes the model yield incremental audio
        chunks (every ~STREAM_INTERVAL_SEC of audio) instead of one final blob."""
        if self._model is None:
            self._ensure_kind_impl(self.cfg.speaker)
        voice = self.cfg.speaker
        max_tokens = _max_tokens_for(text)   # bound runaway generation (no hang)
        stream_kw = (
            {"stream": True, "streaming_interval": STREAM_INTERVAL_SEC}
            if stream else {}
        )
        if self._kind_for_voice(voice) == "base":
            wav, ref = self._ref_for(voice)
            if not wav or not ref:
                raise RuntimeError(f"clone {voice!r} missing wav/ref_text")
            # `instruct` is an emotion/style hint ("smiling, cheerful", "angry")
            # — it shapes HOW the cloned voice speaks; the ref_audio sets WHO.
            return self._model.generate(
                text,
                ref_audio=wav,
                ref_text=ref,
                instruct=self._instruct_for(voice),
                lang_code="auto",
                max_tokens=max_tokens,
                **stream_kw,
                **self._gen_kwargs_for(voice),
            )
        # generate_custom_voice has no `speed` arg (only generate() does).
        return self._model.generate_custom_voice(
            text,
            speaker=voice,
            instruct=self.cfg.instruct,
            max_tokens=max_tokens,
            **stream_kw,
        )

    def _synthesize_impl(self, text: str) -> np.ndarray:
        chunks: list[np.ndarray] = []
        for result in self._build_gen(text, stream=False):
            arr = _to_numpy(getattr(result, "audio", None))
            if arr.size:
                chunks.append(arr)
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)

    def _synthesize_stream_impl(self, text, should_stop, q) -> None:
        """Drive the streaming generator on the executor thread, pushing each
        audio chunk onto `q`. Polls `should_stop` between chunks and closes the
        generator early (freeing this thread for the next request) when set."""
        gen = None
        try:
            gen = self._build_gen(text, stream=True)
            for result in gen:
                if should_stop is not None and should_stop():
                    break
                arr = _to_numpy(getattr(result, "audio", None))
                if arr.size:
                    q.put(arr)
        finally:
            if gen is not None and hasattr(gen, "close"):
                gen.close()   # cooperative cancel of the model generator
            q.put(_STREAM_DONE)
