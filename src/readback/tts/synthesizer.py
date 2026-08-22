"""Synthesizer — TTS facade.

CSM-1B is the sole engine. This thin facade keeps the surface the server depends
on (`synthesize`, `sample_rate`, `current_voice`, `swap_voice`,
`set_temperature`, `load`) so a future engine (e.g. a MisoTTS-8B MLX port) is a
factory change, not a server rewrite.
"""
from __future__ import annotations

import numpy as np

from readback.config import TTSConfig
from readback.tts.csm_engine import CsmEngine

__all__ = ["Synthesizer"]


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

    def swap_voice(self, voice: str) -> str:
        return self._engine.swap_voice(voice)

    def set_temperature(self, temp: float) -> None:
        """Set the CSM delivery temperature for subsequent synth calls (reading
        tone). Read fresh by the sampler each synth; reads are serialized so a
        plain set is safe."""
        self._engine.set_temperature(temp)

    def synthesize(self, text: str) -> np.ndarray:
        return self._engine.synthesize(text)

    def synthesize_batch(self, items: list[tuple[str, float]]) -> list[np.ndarray]:
        """Synthesize several (text, temperature) chunks in one frame loop.
        Audio comes back in input order. See `CsmEngine.synthesize_batch` — this
        is the throughput path; `synthesize` remains the one-chunk fallback."""
        return self._engine.synthesize_batch(items)

    @property
    def batch_size(self) -> int:
        return max(1, int(getattr(self.cfg.csm, "batch_size", 1) or 1))
