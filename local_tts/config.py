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
    voice: str = "af_heart"
    lang_code: str = "a"
    speed: float = 1.0
    torch_device: Literal["mps", "cpu", "auto"] = "cpu"


class WhisperConfig(BaseModel):
    model: str = "medium"
    compute_type: Literal["int8", "float16", "float32"] = "int8"
    beam_size: int = 5


class VADConfig(BaseModel):
    aggressiveness: int = Field(2, ge=0, le=3)


class UIConfig(BaseModel):
    history_turns: int = 10


class Config(BaseModel):
    ollama: OllamaConfig = OllamaConfig()
    kokoro: KokoroConfig = KokoroConfig()
    whisper: WhisperConfig = WhisperConfig()
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
        # Drop unknown top-level keys so old config.yaml files with cli-only
        # sections (audio, input) don't cause validation errors.
        known = cls.model_fields.keys()
        data = {k: v for k, v in data.items() if k in known}
        return cls(**data)
