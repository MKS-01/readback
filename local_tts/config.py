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


class CSMConfig(BaseModel):
    speaker_id: int = 0
    temperature: float = 0.9
    max_audio_ms: int = 15_000
    voice_prompt: Optional[str] = "conversational_a"
    torch_device: Literal["mps", "cpu", "auto"] = "auto"
    repo_path: str = "vendor/csm"


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


class UIConfig(BaseModel):
    default_mode: Literal["voice", "text"] = "voice"
    toggle_key: str = "f4"
    history_turns: int = 10


class Config(BaseModel):
    ollama: OllamaConfig = OllamaConfig()
    csm: CSMConfig = CSMConfig()
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
