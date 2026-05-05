from typing import Optional

import numpy as np

from local_tts.config import WhisperConfig


class Transcriber:
    def __init__(self, cfg: WhisperConfig):
        self.cfg = cfg
        self._model = None

    def load(self):
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            self.cfg.model,
            device="cpu",  # CTranslate2 ARM NEON is fastest path on Apple Silicon
            compute_type=self.cfg.compute_type,
        )

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if self._model is None:
            self.load()
        if audio.size == 0:
            return ""
        audio = audio.astype(np.float32)
        if sample_rate != 16000:
            # faster-whisper expects 16kHz; resample if needed
            audio = self._resample(audio, sample_rate, 16000)

        segments, _info = self._model.transcribe(
            audio,
            language="en",
            beam_size=1,           # greedy — lower latency
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text

    @staticmethod
    def _resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
        if src == dst:
            return audio
        # Simple linear resampling — adequate for VAD-trimmed speech
        ratio = dst / src
        new_len = int(len(audio) * ratio)
        x_old = np.linspace(0.0, 1.0, len(audio), endpoint=False)
        x_new = np.linspace(0.0, 1.0, new_len, endpoint=False)
        return np.interp(x_new, x_old, audio).astype(np.float32)
