import os
from typing import Optional

import numpy as np

from local_tts.config import KokoroConfig

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _select_device(pref: str) -> str:
    import torch

    if pref == "cpu":
        return "cpu"
    if pref == "mps":
        return "mps" if torch.backends.mps.is_available() else "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class Synthesizer:
    """Kokoro-82M TTS wrapper. Stateless across calls (no conversational context)."""

    def __init__(self, cfg: KokoroConfig):
        self.cfg = cfg
        self.device: Optional[str] = None
        self._pipeline = None
        self._sample_rate: int = 24000

    def load(self):
        from kokoro import KPipeline

        self.device = _select_device(self.cfg.torch_device)
        self._pipeline = KPipeline(lang_code=self.cfg.lang_code, device=self.device)
        # Warm voice pack so first synth doesn't pay the download cost
        self._pipeline.load_voice(self.cfg.voice)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def synthesize(self, text: str) -> np.ndarray:
        if self._pipeline is None:
            self.load()
        text = text.strip()
        if not text:
            return np.zeros(0, dtype=np.float32)

        chunks: list[np.ndarray] = []
        for _, _, audio in self._pipeline(
            text, voice=self.cfg.voice, speed=self.cfg.speed
        ):
            if audio is None:
                continue
            if hasattr(audio, "detach"):
                audio = audio.detach().cpu().numpy()
            chunks.append(np.asarray(audio, dtype=np.float32))

        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)

    def reset_context(self):
        # Kokoro is stateless — nothing to reset.
        pass
