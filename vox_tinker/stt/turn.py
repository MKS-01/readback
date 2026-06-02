"""Smart-Turn v3 semantic end-of-turn detection.

Runs pipecat-ai's Smart-Turn v3 ONNX model (Whisper-tiny encoder + linear
classifier, ~8M params) directly via onnxruntime — no pipecat dependency. Given
a window of recent audio it returns P(the speaker has finished their turn), used
to confirm a webrtcvad pause is a real end-of-turn vs. a mid-thought pause.

Contract (from pipecat-ai/smart-turn inference.py):
  - input: WhisperFeatureExtractor(chunk_length=8) log-mel → tensor
    "input_features" of shape (1, 80, 800), float32, 16 kHz, do_normalize=True,
    audio padded/truncated to the LAST 8 s.
  - output: single sigmoid probability; >= threshold (0.5) ⇒ turn complete.

Loading is lazy and may raise TurnDetectorUnavailable (missing deps or the model
can't be downloaded). Callers should catch it and fall back to VAD-only.
"""
from __future__ import annotations

import logging
import threading

import numpy as np

from vox_tinker.config import TurnConfig
from vox_tinker.stt.base import resample

log = logging.getLogger("vox_tinker.turn")

_SR = 16000
_MAX_SECONDS = 8
_MAX_SAMPLES = _SR * _MAX_SECONDS


class TurnDetectorUnavailable(Exception):
    """Raised when the Smart-Turn model or its deps can't be loaded."""


class TurnDetector:
    def __init__(self, cfg: TurnConfig):
        self.cfg = cfg
        self._session = None
        self._fe = None
        self._lock = threading.Lock()   # serialize onnx run + load
        self._loaded = False

    def load(self):
        """Download + initialize the ONNX session and feature extractor.
        Raises TurnDetectorUnavailable on any failure."""
        with self._lock:
            if self._loaded:
                return
            try:
                import onnxruntime as ort
                from huggingface_hub import hf_hub_download
                from transformers import WhisperFeatureExtractor
            except Exception as e:  # pragma: no cover - import guard
                raise TurnDetectorUnavailable(f"missing dependency: {e}") from e
            try:
                path = hf_hub_download(self.cfg.repo_id, self.cfg.model_file)
                self._session = ort.InferenceSession(
                    path, providers=["CPUExecutionProvider"],
                )
                self._fe = WhisperFeatureExtractor(chunk_length=_MAX_SECONDS)
            except Exception as e:
                raise TurnDetectorUnavailable(
                    f"could not load Smart-Turn {self.cfg.model_file!r}: {e}"
                ) from e
            self._loaded = True
            log.info("Smart-Turn ready (%s)", self.cfg.model_file)

    def probability(self, audio: np.ndarray, sample_rate: int = 16000) -> float:
        """P(turn complete) over the last 8 s of `audio` (float32 [-1, 1])."""
        if not self._loaded:
            self.load()
        audio = audio.astype(np.float32)
        if sample_rate != _SR:
            audio = resample(audio, sample_rate, _SR)
        if len(audio) > _MAX_SAMPLES:
            audio = audio[-_MAX_SAMPLES:]
        inputs = self._fe(
            audio,
            sampling_rate=_SR,
            return_tensors="np",
            padding="max_length",
            max_length=_MAX_SAMPLES,
            truncation=True,
            do_normalize=True,
        )
        feat = inputs.input_features.squeeze(0).astype(np.float32)[None, ...]
        with self._lock:
            outputs = self._session.run(None, {"input_features": feat})
        return float(np.asarray(outputs[0]).reshape(-1)[0])

    def is_complete(self, audio: np.ndarray, sample_rate: int = 16000) -> bool:
        return self.probability(audio, sample_rate) >= self.cfg.threshold
