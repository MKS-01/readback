import os
import threading
import warnings
from typing import Optional

import numpy as np

from local_tts.config import KokoroConfig

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Kokoro's model definitions emit harmless warnings on every load:
#  - RNN dropout=0.2 with num_layers=1 (dropout is a no-op there)
#  - torch.nn.utils.weight_norm deprecated in favor of parametrizations
# Both are internal to Kokoro/PyTorch and don't affect runtime correctness.
warnings.filterwarnings(
    "ignore",
    message=".*dropout option adds dropout after all but last recurrent layer.*",
)
warnings.filterwarnings(
    "ignore",
    message=".*torch\\.nn\\.utils\\.weight_norm.*deprecated.*",
    category=FutureWarning,
)

# Curated voice list exposed via the web UI's runtime picker. Voice name format
# is `{lang}{gender}_{name}` — first letter must match KPipeline's lang_code,
# so we re-init the pipeline when switching between American ('a') and
# British ('b') voices. Order here is the order shown in the dropdown.
SUPPORTED_VOICES: tuple[tuple[str, str], ...] = (
    ("af_heart",    "Heart — US female ★"),
    ("af_bella",    "Bella — US female ★"),
    ("af_nicole",   "Nicole — US female"),
    ("af_sarah",    "Sarah — US female"),
    ("af_aoede",    "Aoede — US female"),
    ("af_kore",     "Kore — US female"),
    ("af_nova",     "Nova — US female"),
    ("af_sky",      "Sky — US female"),
    ("am_michael",  "Michael — US male"),
    ("am_adam",     "Adam — US male"),
    ("am_echo",     "Echo — US male"),
    ("am_puck",     "Puck — US male"),
    ("bf_emma",     "Emma — UK female ★"),
    ("bf_isabella", "Isabella — UK female"),
    ("bf_alice",    "Alice — UK female"),
    ("bf_lily",     "Lily — UK female"),
    ("bm_george",   "George — UK male"),
    ("bm_lewis",    "Lewis — UK male"),
    ("bm_daniel",   "Daniel — UK male"),
    ("bm_fable",    "Fable — UK male"),
)
SUPPORTED_VOICE_NAMES: tuple[str, ...] = tuple(v for v, _ in SUPPORTED_VOICES)


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
        # Serializes pipeline (re)construction during a voice swap so an
        # in-flight synth can't race a `KPipeline(...)` ctor. Reads of
        # `self._pipeline` in `synthesize()` are an atomic single-attr load.
        self._swap_lock = threading.Lock()

    def load(self):
        from kokoro import KPipeline

        self.device = _select_device(self.cfg.torch_device)
        with self._swap_lock:
            # Pass repo_id explicitly to suppress Kokoro's "Defaulting repo_id..." warning.
            self._pipeline = KPipeline(
                lang_code=self.cfg.lang_code,
                repo_id="hexgrad/Kokoro-82M",
                device=self.device,
            )
            # Warm voice pack so first synth doesn't pay the download cost
            self._pipeline.load_voice(self.cfg.voice)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def current_voice(self) -> str:
        return self.cfg.voice

    def swap_voice(self, voice: str) -> str:
        """Switch to a different Kokoro voice. Rebuilds KPipeline when the
        voice's language prefix differs from the current `lang_code` (e.g.
        `af_heart` → `bf_emma` flips 'a' → 'b'). Returns the loaded voice."""
        from kokoro import KPipeline

        if voice not in SUPPORTED_VOICE_NAMES:
            raise ValueError(
                f"Unsupported voice {voice!r}; pick from {SUPPORTED_VOICE_NAMES}"
            )
        new_lang = voice[0]
        with self._swap_lock:
            if self._pipeline is None or new_lang != self.cfg.lang_code:
                self._pipeline = KPipeline(
                    lang_code=new_lang,
                    repo_id="hexgrad/Kokoro-82M",
                    device=self.device or _select_device(self.cfg.torch_device),
                )
                self.cfg.lang_code = new_lang
            self._pipeline.load_voice(voice)
            self.cfg.voice = voice
        return voice

    def synthesize(self, text: str) -> np.ndarray:
        if self._pipeline is None:
            self.load()
        text = text.strip()
        if not text:
            return np.zeros(0, dtype=np.float32)

        # Snapshot pipeline + voice under one read so a mid-call swap can't
        # mismatch them.
        pipeline = self._pipeline
        voice = self.cfg.voice

        chunks: list[np.ndarray] = []
        for _, _, audio in pipeline(text, voice=voice, speed=self.cfg.speed):
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
