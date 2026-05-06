from pathlib import Path
from typing import Optional, Literal

import yaml
from pydantic import BaseModel, Field


class OllamaConfig(BaseModel):
    model: str = "qwen3:8b"
    host: str = "http://localhost:11434"
    system_prompt: str = (
        "You are a conversational voice assistant. Speak naturally and concisely. "
        "Use complete sentences. Avoid bullet points, markdown, or special characters. "
        "Keep responses under 3-4 sentences unless asked for more depth."
    )


class KokoroConfig(BaseModel):
    voice: str = "af_heart"                          # af_heart, af_bella, am_michael, bf_emma, ...
    lang_code: str = "a"                             # 'a'=American, 'b'=British, 'j'=Japanese, ...
    speed: float = 1.0
    # CPU is faster than MPS for Kokoro: the iSTFT op falls back to CPU on MPS
    # and the transfer overhead dominates on this 82M model.
    torch_device: Literal["mps", "cpu", "auto"] = "cpu"


class WhisperConfig(BaseModel):
    model: str = "base.en"
    compute_type: Literal["int8", "float16", "float32"] = "int8"


class AudioConfig(BaseModel):
    sample_rate: int = 16000
    output_sample_rate: int = 24000
    input_device: Optional[int] = None
    output_device: Optional[int] = None


class VADConfig(BaseModel):
    aggressiveness: int = Field(2, ge=0, le=3)
    silence_threshold_ms: int = 700
    speech_trigger_ms: int = 300
    # Interrupt-during-AI-speech tuning (echo from speaker bleeds into mic).
    allow_interrupt: bool = True
    interrupt_speech_ms: int = 900          # how long sustained speech must last to interrupt
    interrupt_rms_threshold: float = 0.05   # min loudness (0-1) — gates out speaker bleed


class UIConfig(BaseModel):
    default_mode: Literal["voice", "text"] = "voice"
    toggle_key: str = "f4"
    history_turns: int = 10


class Config(BaseModel):
    ollama: OllamaConfig = OllamaConfig()
    kokoro: KokoroConfig = KokoroConfig()
    whisper: WhisperConfig = WhisperConfig()
    audio: AudioConfig = AudioConfig()
    vad: VADConfig = VADConfig()
    ui: UIConfig = UIConfig()

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        if path is None:
            path = Path("config.yaml")
        if not path.exists():
            return cls()
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)
