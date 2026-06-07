"""CSM-1B via csm-mlx (senstella/csm-mlx).

Dedicated MLX implementation of Sesame's Conversational Speech Model — same
author as parakeet-mlx. Replaces the mlx-audio "sesame" path in v0.7.x for
cleaner output. Output is float32 @ 24 kHz (Mimi-native), matching the WS
contract with no resample.

The two UI voices map to CSM speaker IDs: conversational_a → 0, conversational_b
→ 1. Each sentence is conditioned on the built-in Sesame prompt clip for the
active voice (cached `Segment`, see `_ref_for`) — CSM needs this reference to
sound good AND stay consistent; empty-context generation drifts to a different
voice each sentence and degrades quality. csm-mlx is efficient enough that the
~10 s prompt prefill still runs at RTF ~0.8 on M5 (no underrun).

MLX binds its GPU stream to the first thread that touches the device, so ALL
model work (load + synth) runs on a single owned executor thread; public methods
submit and block. `_impl` methods run ON that thread and must never re-submit.
"""
import concurrent.futures
import queue
from collections.abc import Iterator
from typing import Callable, Optional, TypeVar

import numpy as np

from local_tts.config import CsmTTSConfig

# (id, label) pairs for the UI picker → CSM speaker id. IDs kept stable for prefs
# back-compat, but they point at Sesame's READ-SPEECH prompts (fluent literary
# reading) — the casual "conversational_*" clips made CSM read in a halting,
# chatty tone that sounded unnatural for an article reader.
SUPPORTED_VOICES: tuple[tuple[str, str], ...] = (
    ("conversational_a", "Reading voice A ★"),
    ("conversational_b", "Reading voice B"),
)
SUPPORTED_VOICE_NAMES: tuple[str, ...] = tuple(v for v, _ in SUPPORTED_VOICES)
_VOICE_SPEAKER: dict[str, int] = {"conversational_a": 0, "conversational_b": 1}

_SAMPLE_RATE = 24000  # CSM/Mimi native rate — matches the WS Float32 contract.
_HF_REPO = "senstella/csm-1b-mlx"
_HF_FILE = "ckpt.safetensors"

# CSM needs a voice reference to sound good AND stay consistent — empty-context
# generation picks a fresh voice every sentence. These are Sesame's READ-SPEECH
# prompt clips (sesame/csm-1b), with their EXACT transcripts (transcribed once
# via Parakeet). Fluent literary reading → CSM reads in a natural, even tone. We
# cache a Segment per voice and pass it as context to every sentence.
_HF_PROMPT_REPO = "sesame/csm-1b"
_PROMPTS: dict[str, tuple[str, str]] = {
    "conversational_a": (
        "prompts/read_speech_a.wav",
        "and Lake turned round upon me, a little abruptly, with his odd yellowish "
        "eyes, a little like those of the sea eagle, and the ghost of his smile "
        "that flickered on his singularly pale face with a stern and insidious "
        "look, confronted me.",
    ),
    "conversational_b": (
        "prompts/read_speech_b.wav",
        "He was such a big boy that he wore high boots and carried a jackknife. He "
        "gazed and gazed at the cap, and could not keep from fingering the blue "
        "tassel.",
    ),
}

# csm-mlx stream_generate yields every `accumulation_size` frames (80 ms each).
STREAM_ACCUMULATION = 4

# precision name → mlx dtype attr (fp32 = leave as loaded).
_PRECISION_DTYPES = {"fp16": "float16", "bf16": "bfloat16"}

# Sentinel pushed onto the engine→caller bridge queue when a streamed synth ends.
_STREAM_DONE = object()

_T = TypeVar("_T")


def _max_ms_for(text: str, cap_ms: int) -> int:
    """Bound runaway generation if EOS never fires (keeps frames under CSM's 2048
    token budget). ~120 ms/char + floor, capped at cfg.max_audio_length_ms."""
    return min(cap_ms, max(3000, len(text) * 120))


def _to_numpy(audio) -> np.ndarray:
    """Coerce an mlx/np audio array to 1-D float32."""
    if audio is None:
        return np.zeros(0, dtype=np.float32)
    return np.asarray(audio, dtype=np.float32).reshape(-1)


class CsmEngine:
    name = "csm"

    def __init__(self, cfg: CsmTTSConfig):
        self.cfg = cfg
        self._model = None
        # Cached reference Segment per voice (built once on the executor thread).
        self._ref_cache: dict = {}
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="csm-tts",
        )

    def _run(self, fn: Callable[..., _T], *args) -> _T:
        return self._executor.submit(fn, *args).result()

    # ---- public surface (called from any thread) ----

    @property
    def sample_rate(self) -> int:
        return _SAMPLE_RATE

    @property
    def current_voice(self) -> str:
        return self.cfg.speaker

    @property
    def supported_voices(self) -> tuple[tuple[str, str], ...]:
        return SUPPORTED_VOICES

    def load(self):
        self._run(self._load_impl)

    def swap_voice(self, voice: str) -> str:
        """Switch the active voice (speaker id). Instant — one loaded model, the
        speaker id is just a per-call arg (no reload)."""
        if voice not in _VOICE_SPEAKER:
            raise ValueError(
                f"Unsupported voice {voice!r}; pick from {SUPPORTED_VOICE_NAMES}"
            )
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

        Generation runs on the single MLX executor thread (MLX is not multi-thread
        safe); chunks cross to this caller via a bounded queue. The caller MUST
        drain to completion — pass `should_stop` (polled on the executor thread)
        to end generation early instead of breaking the loop."""
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
        # Stateless across turns (empty context per sentence). Nothing to reset.
        pass

    # ---- impls (run ON the MLX executor thread; never re-submit) ----

    def _speaker_id(self) -> int:
        return _VOICE_SPEAKER.get(self.cfg.speaker, 0)

    def _make_sampler(self):
        from mlx_lm.sample_utils import make_sampler

        return make_sampler(temp=self.cfg.temperature, top_k=self.cfg.top_k)

    def _ref_for(self, voice: str) -> list:
        """Cached reference-prompt context for `voice` (built once on the executor
        thread). Returns [Segment] to pass to generate(), or [] if no prompt is
        configured. `cfg.ref_max_sec` (None/0 = full) trims the clip AND its
        transcript together — a mismatched (text, audio) pair garbles the voice."""
        cached = self._ref_cache.get(voice)
        if cached is not None:
            return cached
        prompt = _PROMPTS.get(voice)
        if prompt is None:
            self._ref_cache[voice] = []
            return []
        import mlx.core as mx
        from huggingface_hub import hf_hub_download
        from csm_mlx import Segment
        from csm_mlx.utils import read_audio

        filename, text = prompt
        wav = hf_hub_download(repo_id=_HF_PROMPT_REPO, filename=filename)
        audio = read_audio(wav, _SAMPLE_RATE)            # (samples,) mx.array @ 24k
        ref_sec = self.cfg.ref_max_sec or 0.0
        if ref_sec:
            cap = int(ref_sec * _SAMPLE_RATE)
            full_sec = audio.shape[0] / _SAMPLE_RATE
            if full_sec > ref_sec:
                audio = audio[:cap]
                words = text.split()
                keep = max(4, int(len(words) * ref_sec / max(1.0, full_sec)))
                text = " ".join(words[:keep])
        mx.eval(audio)
        seg = [Segment(speaker=_VOICE_SPEAKER.get(voice, 0), text=text, audio=audio)]
        self._ref_cache[voice] = seg
        return seg

    def _load_impl(self):
        if self._model is not None:
            return
        from csm_mlx import CSM, csm_1b
        from huggingface_hub import hf_hub_download

        self._model = CSM(csm_1b())
        self._model.load_weights(hf_hub_download(repo_id=_HF_REPO, filename=_HF_FILE))
        # Precision: bf16 by default — ~halves F32 compute, native on Apple Silicon
        # (no per-op dequant), and keeps the voice clean. "fp32" stays full
        # precision (slow); "fp16" a touch faster, narrower range.
        dtype_name = _PRECISION_DTYPES.get((self.cfg.precision or "bf16").lower())
        if dtype_name is not None:
            try:
                import mlx.core as mx

                self._model.set_dtype(getattr(mx, dtype_name))
                mx.eval(self._model.parameters())
            except Exception:
                pass   # fall back to loaded precision rather than failing load
        # Warm the graph (one throwaway synth) AND build the reference cache so
        # the first real sentence is fast and on-voice.
        try:
            import mlx.core as mx
            from csm_mlx import generate

            mx.eval(generate(
                self._model, text="Hello.", speaker=self._speaker_id(),
                context=self._ref_for(self.cfg.speaker), max_audio_length_ms=2000,
                sampler=self._make_sampler(),
            ))
        except Exception:
            pass

    def _synthesize_impl(self, text: str) -> np.ndarray:
        import mlx.core as mx
        from csm_mlx import generate

        if self._model is None:
            self._load_impl()
        audio = generate(
            self._model,
            text=text,
            speaker=self._speaker_id(),
            context=self._ref_for(self.cfg.speaker),
            max_audio_length_ms=_max_ms_for(text, self.cfg.max_audio_length_ms),
            sampler=self._make_sampler(),
        )
        mx.eval(audio)
        return _to_numpy(audio)

    def _synthesize_stream_impl(self, text, should_stop, q) -> None:
        """Drive csm-mlx's stream_generate on the executor thread, pushing each
        audio chunk onto `q`. Polls `should_stop` between chunks."""
        gen = None
        try:
            from csm_mlx import stream_generate

            if self._model is None:
                self._load_impl()
            gen = stream_generate(
                self._model,
                text=text,
                speaker=self._speaker_id(),
                context=self._ref_for(self.cfg.speaker),
                max_audio_length_ms=_max_ms_for(text, self.cfg.max_audio_length_ms),
                accumulation_size=STREAM_ACCUMULATION,
                sampler=self._make_sampler(),
            )
            for chunk in gen:
                if should_stop is not None and should_stop():
                    break
                arr = _to_numpy(chunk)
                if arr.size:
                    q.put(arr)
        finally:
            if gen is not None and hasattr(gen, "close"):
                try:
                    gen.close()
                except Exception:
                    pass
            q.put(_STREAM_DONE)
