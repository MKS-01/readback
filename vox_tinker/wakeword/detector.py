"""Thin wrapper around openWakeWord.

The library is imported lazily so users who haven't installed it can still
run the app in VAD/PTT mode without an ImportError at boot. Calling
``WakeWordDetector.load()`` is what actually pulls onnxruntime + the model.

Frame contract: ``process_int16(frame: bytes)`` accepts arbitrary-length
int16 mono PCM chunks at 16kHz. The detector internally buffers to its
preferred 1280-sample (80ms) chunks, so callers don't have to.
"""
from __future__ import annotations

import logging
import os

import numpy as np

log = logging.getLogger("vox_tinker.wakeword")

# openWakeWord works in 80ms blocks at 16kHz.
_BLOCK_SAMPLES = 1280
_SAMPLE_RATE = 16000


class WakeWordUnavailable(RuntimeError):
    """Raised when openwakeword is requested but not installed or unloadable."""


class WakeWordDetector:
    def __init__(self, model: str, threshold: float):
        self.model_name = model
        self.threshold = threshold
        self._model = None
        self._buf: list[np.ndarray] = []
        self._buf_len = 0
        # Updated each time we cross the threshold so callers can throttle.
        self.last_score: float = 0.0

    def load(self) -> None:
        """Loads onnxruntime + the wake-word model. Raises WakeWordUnavailable
        on import or load failure so the caller can fall back to VAD mode."""
        if self._model is not None:
            return
        try:
            import openwakeword  # type: ignore
            from openwakeword.model import Model  # type: ignore
            from openwakeword.utils import download_models  # type: ignore
        except Exception as e:  # pragma: no cover — environment-specific
            raise WakeWordUnavailable(
                f"openwakeword not installed or failed to import: {e}"
            ) from e

        # Pick framework: .tflite path → tflite; everything else (built-in name
        # or .onnx file) → onnx. tflite-runtime has no Apple-Silicon wheel, so
        # for built-in models we always go through onnxruntime which we install
        # as part of the `[wakeword]` extras.
        is_custom_path = os.path.exists(self.model_name)
        if is_custom_path and self.model_name.endswith(".tflite"):
            framework = "tflite"
        else:
            framework = "onnx"

        # Built-in models aren't bundled with the wheel — fetch them on first
        # use. download_models() pulls both .tflite and .onnx variants plus the
        # shared feature models; it's a no-op when files already exist.
        if not is_custom_path and self.model_name in openwakeword.MODELS:
            try:
                download_models([self.model_name])
            except Exception as e:
                raise WakeWordUnavailable(
                    f"failed to download wake-word model {self.model_name!r}: {e}"
                ) from e

        try:
            self._model = Model(
                wakeword_models=[self.model_name],
                inference_framework=framework,
            )
        except Exception as e:
            raise WakeWordUnavailable(
                f"failed to load wake-word model {self.model_name!r}: {e}"
            ) from e

    def reset(self) -> None:
        """Clear internal buffer + score history. Call on phase transitions
        (e.g. when the AI starts speaking) so stale audio can't trigger."""
        self._buf = []
        self._buf_len = 0
        self.last_score = 0.0
        if self._model is not None and hasattr(self._model, "reset"):
            try:
                self._model.reset()
            except Exception:  # pragma: no cover
                pass

    def process_int16(self, frame: bytes) -> bool:
        """Feed an arbitrary-length int16 PCM chunk and return True if the
        wake-word was detected during this call."""
        if self._model is None:
            return False
        # Convert to int16 numpy. openwakeword's predict() accepts int16.
        arr = np.frombuffer(frame, dtype=np.int16)
        if arr.size == 0:
            return False
        self._buf.append(arr)
        self._buf_len += arr.size

        triggered = False
        while self._buf_len >= _BLOCK_SAMPLES:
            block, leftover = self._take_block()
            try:
                scores = self._model.predict(block)
            except Exception:
                log.exception("wakeword predict failed")
                continue
            # scores is a dict keyed by model name → confidence in [0,1].
            best = max(scores.values()) if scores else 0.0
            self.last_score = best
            if best >= self.threshold:
                triggered = True
                # Don't break: drain the remaining buffer so the next call
                # starts fresh and we don't accumulate the same audio twice.
            self._buf = [leftover] if leftover.size > 0 else []
            self._buf_len = leftover.size
        return triggered

    def _take_block(self) -> tuple[np.ndarray, np.ndarray]:
        """Splice off the first 1280-sample block; return (block, leftover)."""
        concat = np.concatenate(self._buf)
        block = concat[:_BLOCK_SAMPLES]
        leftover = concat[_BLOCK_SAMPLES:]
        return block, leftover
