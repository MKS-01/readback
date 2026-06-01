"""ASR engine abstraction.

`local-tts` ships two interchangeable speech-to-text backends behind a common
surface so the web UI can toggle between them at runtime:

  - ParakeetEngine — NVIDIA Parakeet via parakeet-mlx (default, streaming-capable)
  - WhisperEngine  — faster-whisper / CTranslate2 (batch only)

The `Transcriber` facade (transcriber.py) owns one of each and delegates to the
active engine. This mirrors the `Tool` / `WebSearchProvider` protocol pattern in
`local_tts/tools/`.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class ASREngine(Protocol):
    """The contract every ASR backend implements.

    Implementations must keep a `threading.Lock` swap discipline: a model swap
    serializes the heavy ctor, and `transcribe()` reads the active model under a
    single atomic load so an in-flight call finishes against the old weights.
    """

    # Stable identifier surfaced to the UI ("parakeet" | "whisper").
    name: str
    # Whether start_stream()/feed()/partial_text/finalize() are implemented.
    supports_streaming: bool

    @property
    def supported_models(self) -> tuple[str, ...]:
        """Model ids/names this engine exposes through the runtime picker."""
        ...

    @property
    def current_model(self) -> str:
        ...

    def load(self) -> None:
        """Load the configured model. Idempotent."""
        ...

    def swap_model(self, name: str) -> str:
        """Hot-swap to another model from `supported_models`. Returns the name
        actually loaded. Raises ValueError for unsupported names."""
        ...

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Batch transcription of a float32 PCM window normalized to [-1, 1]."""
        ...


def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Simple linear resampling — adequate for VAD-trimmed speech windows.

    Shared by both engines so the 16 kHz contract is enforced in one place.
    """
    if src == dst:
        return audio
    ratio = dst / src
    new_len = int(len(audio) * ratio)
    x_old = np.linspace(0.0, 1.0, len(audio), endpoint=False)
    x_new = np.linspace(0.0, 1.0, new_len, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)
