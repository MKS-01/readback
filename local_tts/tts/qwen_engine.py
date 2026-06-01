import concurrent.futures
from typing import Callable, Optional, TypeVar

import numpy as np

from local_tts.config import QwenTTSConfig

# Qwen3-TTS CustomVoice preset speakers (from model.get_supported_speakers()).
# (id, label) pairs exposed to the web UI's voice picker.
SUPPORTED_VOICES: tuple[tuple[str, str], ...] = (
    ("ryan",      "Ryan — male ★"),
    ("eric",      "Eric — male"),
    ("aiden",     "Aiden — male"),
    ("dylan",     "Dylan — male"),
    ("uncle_fu",  "Uncle Fu — male"),
    ("serena",    "Serena — female ★"),
    ("vivian",    "Vivian — female"),
    ("ono_anna",  "Ono Anna — female"),
    ("sohee",     "Sohee — female"),
)
SUPPORTED_VOICE_NAMES: tuple[str, ...] = tuple(v for v, _ in SUPPORTED_VOICES)

_SAMPLE_RATE = 24000  # Qwen3-TTS native rate — matches the WS Float32 contract.

_T = TypeVar("_T")


def _to_numpy(audio) -> np.ndarray:
    """Coerce an mlx/torch/np audio array to 1-D float32."""
    if audio is None:
        return np.zeros(0, dtype=np.float32)
    if hasattr(audio, "detach"):           # torch tensor
        audio = audio.detach().cpu().numpy()
    arr = np.asarray(audio, dtype=np.float32)
    return arr.reshape(-1)


class QwenEngine:
    """Qwen3-TTS via mlx-audio. Like Parakeet, MLX binds its GPU stream to the
    thread that first touches the device, so ALL model work (load + synth) runs
    on a single owned executor thread; public methods submit and block."""

    name = "qwen"

    def __init__(self, cfg: QwenTTSConfig):
        self.cfg = cfg
        self._model = None
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="qwen-tts",
        )

    def _run(self, fn: Callable[..., _T], *args) -> _T:
        return self._executor.submit(fn, *args).result()

    @property
    def sample_rate(self) -> int:
        return _SAMPLE_RATE

    @property
    def current_voice(self) -> str:
        return self.cfg.speaker

    @property
    def supported_voices(self) -> tuple[tuple[str, str], ...]:
        return SUPPORTED_VOICES

    def load(self):
        self._run(self._load_impl)

    def swap_voice(self, voice: str) -> str:
        """Switch the active speaker. No model reload — speaker is just a
        per-call argument — so this is instant."""
        if voice not in SUPPORTED_VOICE_NAMES:
            raise ValueError(
                f"Unsupported speaker {voice!r}; pick from {SUPPORTED_VOICE_NAMES}"
            )
        self.cfg.speaker = voice
        return voice

    def synthesize(self, text: str) -> np.ndarray:
        text = text.strip()
        if not text:
            return np.zeros(0, dtype=np.float32)
        return self._run(self._synthesize_impl, text)

    def reset_context(self):
        # Stateless across calls — nothing to reset.
        pass

    # ---- impls (run ON the MLX executor thread) ----

    def _load_impl(self):
        if self._model is not None:
            return
        from mlx_audio.tts.utils import load_model

        self._model = load_model(self.cfg.model)
        # Warm the graph so the first real utterance doesn't pay the ~2s
        # cold-start compile cost.
        try:
            for _ in self._model.generate_custom_voice(
                "Hello.", speaker=self.cfg.speaker,
            ):
                pass
        except Exception:
            pass

    def _synthesize_impl(self, text: str) -> np.ndarray:
        if self._model is None:
            self._load_impl()
        chunks: list[np.ndarray] = []
        # NOTE: generate_custom_voice has no `speed` arg (only generate() does);
        # the UI speed slider is a no-op for Qwen until we wire ref-voice mode.
        for result in self._model.generate_custom_voice(
            text,
            speaker=self.cfg.speaker,
            instruct=self.cfg.instruct,
        ):
            arr = _to_numpy(getattr(result, "audio", None))
            if arr.size:
                chunks.append(arr)
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)
