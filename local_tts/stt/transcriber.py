import warnings
from typing import Optional

import numpy as np

from local_tts.config import WhisperConfig

# faster-whisper's mel-spectrogram step (`mel_filters @ magnitudes`) emits
# RuntimeWarnings when the audio buffer is near-silent: log(0) becomes -inf,
# tiny floats overflow, etc. Whisper handles the resulting NaN/-inf internally
# and still produces a correct transcription, so suppress the noise.
warnings.filterwarnings(
    "ignore",
    message=r"(divide by zero|overflow|invalid value) encountered in matmul",
    category=RuntimeWarning,
)


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
            # Wider beam + best_of substantially improves accuracy on accented
            # English at a modest latency cost. With large-v3-turbo on M-series
            # CPU this still finishes well inside the LLM step.
            beam_size=10,
            best_of=10,
            patience=1.0,
            # Default fallback temperatures; kept explicit so it's obvious we
            # rely on the schedule (0.0 → 1.0) for low-confidence retries.
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            # Reject low-confidence / silent buffers as empty rather than let
            # Whisper hallucinate ("Yeah.", "Thanks for watching.", etc.) on
            # the faint speaker-bleed picked up right after AI speech ends.
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            condition_on_previous_text=False,  # avoid prior-segment bias
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
