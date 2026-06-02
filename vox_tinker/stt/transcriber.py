"""Transcriber — facade over the pluggable ASR engines.

Owns one ParakeetEngine and one WhisperEngine and delegates to whichever is
active (`STTConfig.engine`). The server talks only to this facade, so swapping
engines or models is uniform regardless of backend.

Back-compat: `SUPPORTED_MODELS` is re-exported (Whisper's list) for any importer
that predates the dual-engine split; new code should use
`Transcriber.models_for(engine)` instead.
"""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np

from vox_tinker.config import STTConfig
from vox_tinker.stt.base import ASREngine
from vox_tinker.stt.parakeet_engine import ParakeetEngine
from vox_tinker.stt.whisper_engine import SUPPORTED_MODELS, WhisperEngine  # noqa: F401

ENGINES_AVAILABLE = ("parakeet", "whisper")


class Transcriber:
    def __init__(self, cfg: STTConfig):
        self.cfg = cfg
        # Engine objects are cheap — the heavy model load is deferred to load().
        self._engines: dict[str, ASREngine] = {
            "parakeet": ParakeetEngine(cfg.parakeet),
            "whisper": WhisperEngine(cfg.whisper),
        }
        # Serializes engine switching against an in-flight transcribe.
        self._swap_lock = threading.Lock()

    @property
    def _active(self) -> ASREngine:
        return self._engines[self.cfg.engine]

    @property
    def current_engine(self) -> str:
        return self.cfg.engine

    @property
    def engines_available(self) -> tuple[str, ...]:
        return ENGINES_AVAILABLE

    @property
    def current_model(self) -> str:
        return self._active.current_model

    @property
    def supports_streaming(self) -> bool:
        return self._active.supports_streaming

    def models_for(self, engine: Optional[str] = None) -> tuple[str, ...]:
        eng = self._engines.get(engine or self.cfg.engine)
        return eng.supported_models if eng else ()

    def load(self):
        """Load only the active engine's model."""
        self._active.load()

    def swap_engine(self, engine: str) -> str:
        """Switch the active ASR engine and load its model. Returns the engine
        actually active. The previous engine's model stays resident for a fast
        switch back. Refusal mid-pipeline is enforced by the caller (server)."""
        if engine not in self._engines:
            raise ValueError(
                f"Unsupported ASR engine {engine!r}; pick from {ENGINES_AVAILABLE}"
            )
        with self._swap_lock:
            self.cfg.engine = engine
            target = self._engines[engine]
        target.load()
        return engine

    def swap_model(self, name: str) -> str:
        """Hot-swap the active engine's model."""
        return self._active.swap_model(name)

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        # Snapshot the active engine under one read so a concurrent swap_engine
        # can't redirect a call that's already running.
        engine = self._active
        return engine.transcribe(audio, sample_rate)

    def transcribe_clone_ref(self, path: str, language: Optional[str] = None) -> str:
        """Transcribe a voice-clone reference clip. ALWAYS routes to Whisper
        (multilingual; Parakeet is English-only) regardless of the active live
        STT engine, lazy-loading Whisper if needed. Runs on the caller's thread
        — keep it OFF the MLX/TTS executor thread."""
        whisper = self._engines["whisper"]
        whisper.load()
        return whisper.transcribe_file(path, language=language)

    def streaming_engine(self) -> Optional[ASREngine]:
        """Return the active engine if it supports streaming, else None. The
        caller (Session ASR worker) holds this reference for one utterance so a
        mid-utterance engine swap doesn't redirect an open stream."""
        engine = self._active
        return engine if engine.supports_streaming else None
