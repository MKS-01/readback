import concurrent.futures
from typing import Callable, Optional, TypeVar

import numpy as np

from local_tts.config import ParakeetConfig
from local_tts.stt.base import resample

# Parakeet (MLX) model ids resolved by parakeet-mlx's from_pretrained. These are
# the senstella/mlx-community ports of NVIDIA Parakeet. v2 = English; v3 = 25
# langs; the rnnt/ctc/1.1b variants trade latency for accuracy.
SUPPORTED_MODELS = (
    "mlx-community/parakeet-tdt-0.6b-v2",
    "mlx-community/parakeet-tdt-0.6b-v3",
    "mlx-community/parakeet-tdt-1.1b",
    "mlx-community/parakeet-rnnt-0.6b",
    "mlx-community/parakeet-ctc-0.6b",
)

# Parakeet's preprocessor operates at 16 kHz, matching our WS mic contract.
_TARGET_SR = 16000

_T = TypeVar("_T")


class ParakeetEngine:
    """NVIDIA Parakeet via parakeet-mlx (Metal/MLX). Streaming-capable.

    parakeet-mlx's `transcribe()` is file/ffmpeg-only, but its streaming context
    (`transcribe_stream`) accepts raw 1-D audio samples through `add_audio()` and
    computes the log-mel internally. We therefore route BOTH batch and streaming
    through `transcribe_stream`, feeding `mx.array` PCM directly — no temp wav,
    no ffmpeg dependency.

    MLX/Metal binds its default GPU stream to the thread that first touches the
    device, and operations on any other thread raise "no Stream(gpu, 0) in
    current thread". So this engine owns a **single-thread executor** and runs
    EVERY MLX call (load, batch transcribe, streaming feed/finalize) on that one
    thread. Public methods may be called from any thread — they submit to the
    executor and block. This serializes inference for free (no separate locks)
    and satisfies MLX's single-thread requirement regardless of caller.

    The `_impl` methods assume they are already running on the MLX thread and
    must never re-submit (that would deadlock the single worker).
    """

    name = "parakeet"
    supports_streaming = True

    def __init__(self, cfg: ParakeetConfig):
        self.cfg = cfg
        self._model = None
        self._current_model_name: Optional[str] = None
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="parakeet-mlx",
        )
        # Open streaming context (StreamingParakeet) + its context manager —
        # only ever touched on the executor thread.
        self._stream = None
        self._stream_cm = None
        # Accumulates sub-block audio between add_audio() calls — the encoder
        # underflows on tiny adds, so we buffer to stream_chunk_ms first.
        self._feed_buf: Optional[np.ndarray] = None

    # ---- executor plumbing ----

    def _run(self, fn: Callable[..., _T], *args) -> _T:
        """Run `fn` on the dedicated MLX thread and block for its result."""
        return self._executor.submit(fn, *args).result()

    # ---- read-only properties (no MLX work) ----

    @property
    def supported_models(self) -> tuple[str, ...]:
        return SUPPORTED_MODELS

    @property
    def current_model(self) -> str:
        return self._current_model_name or self.cfg.model

    @property
    def _context_size(self) -> tuple[int, int]:
        return (self.cfg.context_left, self.cfg.context_right)

    @property
    def _chunk_samples(self) -> int:
        return max(1, int(_TARGET_SR * self.cfg.stream_chunk_ms / 1000))

    # ---- public API (callable from any thread) ----

    def load(self):
        self._run(self._load_impl)

    def swap_model(self, name: str) -> str:
        if name not in SUPPORTED_MODELS:
            raise ValueError(
                f"Unsupported Parakeet model {name!r}; pick from {SUPPORTED_MODELS}"
            )
        return self._run(self._swap_impl, name)

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if audio.size == 0:
            return ""
        return self._run(self._transcribe_impl, audio, sample_rate)

    def start_stream(self):
        self._run(self._start_stream_impl)

    def feed(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        return self._run(self._feed_impl, audio, sample_rate)

    @property
    def partial_text(self) -> str:
        if self._stream is None:
            return ""
        return self._run(self._partial_impl)

    def finalize(self) -> str:
        return self._run(self._finalize_impl)

    def abort_stream(self):
        self._run(self._abort_impl)

    # ---- impls (run ON the MLX executor thread; never re-submit) ----

    def _load_impl(self):
        from parakeet_mlx import from_pretrained

        if self._model is not None and self._current_model_name == self.cfg.model:
            return
        self._model = from_pretrained(self.cfg.model)
        self._current_model_name = self.cfg.model

    def _swap_impl(self, name: str) -> str:
        from parakeet_mlx import from_pretrained

        if self._current_model_name == name and self._model is not None:
            return name
        self._abort_impl()  # drop any open stream bound to the old model
        self._model = from_pretrained(name)
        self._current_model_name = name
        self.cfg.model = name
        return name

    def _transcribe_impl(self, audio: np.ndarray, sample_rate: int) -> str:
        import mlx.core as mx

        if self._model is None:
            self._load_impl()
        audio = audio.astype(np.float32)
        if sample_rate != _TARGET_SR:
            audio = resample(audio, sample_rate, _TARGET_SR)
        with self._model.transcribe_stream(context_size=self._context_size) as stream:
            stream.add_audio(mx.array(audio))
            text = stream.result.text
        return (text or "").strip()

    def _start_stream_impl(self):
        if self._model is None:
            self._load_impl()
        self._abort_impl()
        self._stream_cm = self._model.transcribe_stream(context_size=self._context_size)
        self._stream = self._stream_cm.__enter__()
        self._feed_buf = None

    def _feed_impl(self, audio: np.ndarray, sample_rate: int) -> str:
        if self._stream is None:
            self._start_stream_impl()
        audio = audio.astype(np.float32)
        if sample_rate != _TARGET_SR:
            audio = resample(audio, sample_rate, _TARGET_SR)
        self._feed_buf = (
            audio if self._feed_buf is None
            else np.concatenate([self._feed_buf, audio])
        )
        if len(self._feed_buf) < self._chunk_samples:
            return self._partial_impl()  # not enough yet — report last result
        block, self._feed_buf = self._feed_buf, None
        return self._add_block_impl(block)

    def _add_block_impl(self, block: np.ndarray) -> str:
        import mlx.core as mx

        self._stream.add_audio(mx.array(block))
        return (self._stream.result.text or "").strip()

    def _partial_impl(self) -> str:
        if self._stream is None:
            return ""
        return (self._stream.result.text or "").strip()

    def _finalize_impl(self) -> str:
        if self._stream is None:
            return ""
        if self._feed_buf is not None and len(self._feed_buf) > 0:
            try:
                self._add_block_impl(self._feed_buf)
            except Exception:
                pass  # keep whatever partial we already have
            self._feed_buf = None
        text = (self._stream.result.text or "").strip()
        self._abort_impl()
        return text

    def _abort_impl(self):
        if self._stream_cm is not None:
            try:
                self._stream_cm.__exit__(None, None, None)
            except Exception:
                pass
        self._stream = None
        self._stream_cm = None
        self._feed_buf = None
