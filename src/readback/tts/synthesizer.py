"""Synthesizer — TTS facade.

CSM-1B (mlx-audio) is the sole engine (Qwen3-TTS was replaced; reference-audio
cloning was removed in v0.7.x — two preset voices only). This thin facade keeps
the surface the web server depends on (`synthesize`, `sample_rate`,
`current_voice`, `swap_voice`, `load`, `reset_context`, `SUPPORTED_VOICES`) so a
future engine (e.g. a MisoTTS-8B MLX port) is a factory change, not a server
rewrite.
"""
from __future__ import annotations

import numpy as np

from readback.config import TTSConfig
from readback.tts.csm_engine import (
    SUPPORTED_VOICES,
    SUPPORTED_VOICE_NAMES,
    CsmEngine,
)

__all__ = [
    "Synthesizer",
    "SUPPORTED_VOICES",
    "SUPPORTED_VOICE_NAMES",
]


class Synthesizer:
    def __init__(self, cfg: TTSConfig):
        self.cfg = cfg
        # Single engine today; selected by cfg.engine for forward-compat with a
        # future engine branch (e.g. "miso").
        self._engine = CsmEngine(cfg.csm)

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
        """Preset speakers as (id, label) pairs."""
        return self._engine.supported_voices

    def swap_voice(self, voice: str) -> str:
        return self._engine.swap_voice(voice)

    def set_temperature(self, temp: float) -> None:
        """Set the CSM delivery temperature for subsequent synth calls (reading
        tone). Read fresh by the sampler each synth; reads are serialized so a
        plain set is safe."""
        self._engine.set_temperature(temp)

    def synthesize(self, text: str) -> np.ndarray:
        return self._engine.synthesize(text)

    def synthesize_stream(self, text: str, should_stop=None):
        """Yield the sentence's audio in chunks as the engine produces them.
        Caller must drain fully; use `should_stop` to end early (see engine)."""
        return self._engine.synthesize_stream(text, should_stop)

    def reset_context(self):
        self._engine.reset_context()
