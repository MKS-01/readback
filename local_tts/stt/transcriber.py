import threading
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

# Models we expose through the web UI's runtime picker. Values here must be
# names that faster-whisper resolves to a CTranslate2 model on HuggingFace
# (see https://github.com/SYSTRAN/faster-whisper for the full list).
SUPPORTED_MODELS = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3-turbo",
    "large-v3",
)


class Transcriber:
    def __init__(self, cfg: WhisperConfig):
        self.cfg = cfg
        self._model = None
        self._current_model_name: Optional[str] = None
        # Serializes the actual `WhisperModel(...)` ctor call across threads
        # (web sessions can both trigger a swap). Reads of `self._model` in
        # `transcribe()` are an atomic single-attr load and don't need it.
        self._swap_lock = threading.Lock()

    @property
    def current_model(self) -> str:
        return self._current_model_name or self.cfg.model

    def load(self):
        from faster_whisper import WhisperModel

        with self._swap_lock:
            if self._model is not None and self._current_model_name == self.cfg.model:
                return
            self._model = WhisperModel(
                self.cfg.model,
                device="cpu",  # CTranslate2 ARM NEON is fastest path on Apple Silicon
                compute_type=self.cfg.compute_type,
            )
            self._current_model_name = self.cfg.model

    def swap_model(self, name: str) -> str:
        """Hot-swap to a different Whisper checkpoint. Blocks while the new
        weights load (~5-15s on first download, ~1-3s if cached). Returns the
        name actually loaded. Safe to call concurrently — the lock serializes
        the load step, and `transcribe()` always reads the latest reference.
        """
        from faster_whisper import WhisperModel

        if name not in SUPPORTED_MODELS:
            raise ValueError(
                f"Unsupported Whisper model {name!r}; pick from {SUPPORTED_MODELS}"
            )
        with self._swap_lock:
            if self._current_model_name == name and self._model is not None:
                return name
            new_model = WhisperModel(
                name, device="cpu", compute_type=self.cfg.compute_type,
            )
            # Atomic ref swap — any in-flight transcribe() finishes against
            # the old model and the next call picks up the new one.
            self._model = new_model
            self._current_model_name = name
            self.cfg.model = name
        return name

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if self._model is None:
            self.load()
        if audio.size == 0:
            return ""
        audio = audio.astype(np.float32)
        if sample_rate != 16000:
            # faster-whisper expects 16kHz; resample if needed
            audio = self._resample(audio, sample_rate, 16000)

        beam = max(1, int(self.cfg.beam_size))
        # Capture the active model under one atomic read so a mid-call swap
        # can't yank it out from under us.
        model = self._model
        segments, _info = model.transcribe(
            audio,
            language="en",
            beam_size=beam,
            best_of=beam,
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
