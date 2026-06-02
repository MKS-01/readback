"""Synthesizer — TTS facade.

Kokoro was removed; Qwen3-TTS (mlx-audio) is the sole engine for now. This thin
facade keeps the surface the web server depends on (`synthesize`, `sample_rate`,
`current_voice`, `swap_voice`, `load`, `reset_context`, `SUPPORTED_VOICES`) so
re-adding a second engine later is a factory change, not a server rewrite.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from local_tts.config import CloneVoiceConfig, TTSConfig
from local_tts.tts.qwen_engine import (
    CLONE_PREFIX,
    SUPPORTED_VOICES,
    SUPPORTED_VOICE_NAMES,
    QwenEngine,
)

__all__ = [
    "Synthesizer",
    "SUPPORTED_VOICES",
    "SUPPORTED_VOICE_NAMES",
    "CLONE_PREFIX",
]


class Synthesizer:
    def __init__(self, cfg: TTSConfig):
        self.cfg = cfg
        # Only one engine today; selected by cfg.engine for forward-compat.
        self._engine = QwenEngine(cfg.qwen)

    def load(self):
        self._engine.load()

    @property
    def sample_rate(self) -> int:
        return self._engine.sample_rate

    @property
    def current_voice(self) -> str:
        return self._engine.current_voice

    @property
    def supported_voices(self) -> tuple[tuple[str, str], ...]:
        """Preset speakers + configured clones, as (id, label) pairs."""
        return self._engine.supported_voices

    def swap_voice(self, voice: str) -> str:
        return self._engine.swap_voice(voice)

    # ---- clone helpers (used by the server's voice-swap handler) ----

    @staticmethod
    def is_clone(voice: str) -> bool:
        return QwenEngine.is_clone(voice)

    def clone_for(self, voice: str) -> Optional[CloneVoiceConfig]:
        return self._engine.clone_for(voice)

    def has_ref_text(self, voice: str) -> bool:
        return self._engine.has_ref_text(voice)

    def set_ref_text(self, name: str, text: str) -> None:
        self._engine.set_ref_text(name, text)

    def synthesize(self, text: str) -> np.ndarray:
        return self._engine.synthesize(text)

    def synthesize_stream(self, text: str, should_stop=None):
        """Yield the sentence's audio in chunks as the engine produces them.
        Caller must drain fully; use `should_stop` to end early (see engine)."""
        return self._engine.synthesize_stream(text, should_stop)

    def reset_context(self):
        self._engine.reset_context()
