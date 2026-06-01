"""Synthesizer — TTS facade.

Kokoro was removed; Qwen3-TTS (mlx-audio) is the sole engine for now. This thin
facade keeps the surface the web server depends on (`synthesize`, `sample_rate`,
`current_voice`, `swap_voice`, `load`, `reset_context`, `SUPPORTED_VOICES`) so
re-adding a second engine later is a factory change, not a server rewrite.
"""
from __future__ import annotations

import numpy as np

from local_tts.config import TTSConfig
from local_tts.tts.qwen_engine import (
    SUPPORTED_VOICES,
    SUPPORTED_VOICE_NAMES,
    QwenEngine,
)

__all__ = ["Synthesizer", "SUPPORTED_VOICES", "SUPPORTED_VOICE_NAMES"]


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

    def swap_voice(self, voice: str) -> str:
        return self._engine.swap_voice(voice)

    def synthesize(self, text: str) -> np.ndarray:
        return self._engine.synthesize(text)

    def reset_context(self):
        self._engine.reset_context()
