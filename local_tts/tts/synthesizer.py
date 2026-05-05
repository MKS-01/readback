import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np

from local_tts.config import CSMConfig

# Must be set BEFORE any torch import to avoid Triton crash on Apple Silicon.
os.environ.setdefault("NO_TORCH_COMPILE", "1")
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _select_device(pref: str) -> str:
    import torch

    if pref == "cpu":
        return "cpu"
    if pref == "mps":
        return "mps" if torch.backends.mps.is_available() else "cpu"
    # auto
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


# Rough audio→token estimate: CSM produces ~12.5 frames/sec, but tokens are
# higher fan-out. We use 80 tokens per second of audio as a safe upper bound.
_AUDIO_TOKENS_PER_SEC = 80
_TEXT_TOKENS_PER_CHAR = 0.3
_CONTEXT_TOKEN_BUDGET = 1500


class Synthesizer:
    def __init__(self, cfg: CSMConfig):
        self.cfg = cfg
        self.device: Optional[str] = None
        self._generator = None
        self._sample_rate: int = 24000
        # Rolling list of CSM Segment objects (last few exchanges)
        self._context: list = []

    def load(self):
        repo_path = Path(self.cfg.repo_path).resolve()
        if not repo_path.exists():
            raise FileNotFoundError(
                f"CSM repo not found at {repo_path}. Run: "
                f"git clone https://github.com/SesameAILabs/csm {self.cfg.repo_path}"
            )
        sys.path.insert(0, str(repo_path))

        import torch

        self.device = _select_device(self.cfg.torch_device)

        # CSM exposes load_csm_1b in generator.py
        from generator import load_csm_1b  # type: ignore

        self._generator = load_csm_1b(device=self.device)
        self._sample_rate = self._generator.sample_rate

        # Cast to bfloat16 on MPS to avoid float64 issues
        if self.device == "mps":
            try:
                self._generator._model = self._generator._model.to(dtype=torch.bfloat16)
            except Exception:
                pass

        # Optional voice prompt seeding for session voice consistency
        if self.cfg.voice_prompt:
            try:
                self._seed_voice_prompt(self.cfg.voice_prompt)
            except Exception:
                # Voice prompt seeding is optional; fall back to random voice
                pass

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def _seed_voice_prompt(self, name: str):
        """Load a CSM-shipped voice prompt from HuggingFace and prepend to context."""
        from huggingface_hub import hf_hub_download
        import torchaudio
        from generator import Segment  # type: ignore

        prompts = {
            "conversational_a": {
                "text": (
                    "like revising for an exam I'd have to try and like keep up the momentum "
                    "because I'd start really early I'd be like okay I'm gonna start by like "
                    "you know reading through the lectures"
                ),
                "audio": "prompts/conversational_a.wav",
            },
            "conversational_b": {
                "text": (
                    "like a super Mario level. Like it's very like high detail. And like, "
                    "once you get into the park, it just like, everything looks like a computer game"
                ),
                "audio": "prompts/conversational_b.wav",
            },
        }
        if name not in prompts:
            return
        info = prompts[name]
        path = hf_hub_download(repo_id="sesame/csm-1b", filename=info["audio"])
        wav, sr = torchaudio.load(path)
        wav = wav.mean(dim=0)  # mono
        if sr != self._sample_rate:
            wav = torchaudio.functional.resample(wav, sr, self._sample_rate)
        seg = Segment(text=info["text"], speaker=self.cfg.speaker_id, audio=wav)
        self._context.insert(0, seg)

    def synthesize(self, text: str) -> np.ndarray:
        if self._generator is None:
            self.load()
        text = text.strip()
        if not text:
            return np.zeros(0, dtype=np.float32)

        from generator import Segment  # type: ignore

        audio_tensor = self._generator.generate(
            text=text,
            speaker=self.cfg.speaker_id,
            context=self._context,
            max_audio_length_ms=self.cfg.max_audio_ms,
            temperature=self.cfg.temperature,
        )

        # Append the new turn to context, then prune
        seg = Segment(text=text, speaker=self.cfg.speaker_id, audio=audio_tensor)
        self._context.append(seg)
        self._prune_context()

        return audio_tensor.detach().to("cpu").float().numpy()

    def reset_context(self):
        self._context = []
        if self.cfg.voice_prompt:
            try:
                self._seed_voice_prompt(self.cfg.voice_prompt)
            except Exception:
                pass

    def _prune_context(self):
        """Trim oldest segments to stay under token budget. Keep voice prompt at index 0."""
        keep_first = 1 if self.cfg.voice_prompt else 0
        while len(self._context) > keep_first + 1 and self._estimate_tokens() > _CONTEXT_TOKEN_BUDGET:
            # Drop the oldest non-prompt segment
            self._context.pop(keep_first)

    def _estimate_tokens(self) -> int:
        total = 0
        for seg in self._context:
            text_tokens = int(len(seg.text) * _TEXT_TOKENS_PER_CHAR)
            audio_seconds = len(seg.audio) / self._sample_rate
            audio_tokens = int(audio_seconds * _AUDIO_TOKENS_PER_SEC)
            total += text_tokens + audio_tokens
        return total
