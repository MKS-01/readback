from pathlib import Path
from typing import Optional, Literal

import yaml
from pydantic import BaseModel, Field


DEFAULT_PERSONA_PROMPT = (
    "You are a conversational voice assistant. Speak naturally and concisely. "
    "Use complete sentences. Avoid bullet points, markdown, or special characters. "
    "Keep responses under 3-4 sentences unless asked for more depth."
)


class OllamaConfig(BaseModel):
    model: str = "qwen3:8b"
    host: str = "http://localhost:11434"
    # Legacy: kept Optional for backward-compatibility with config.yaml files
    # that set `ollama.system_prompt`. At Config.load() time we promote it to
    # the "default" persona if no `persona` section is present.
    system_prompt: Optional[str] = None


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


class Persona(BaseModel):
    name: str
    system_prompt: str


def _default_personas() -> list[Persona]:
    return [
        Persona(name="default", system_prompt=DEFAULT_PERSONA_PROMPT),
        Persona(
            name="concise",
            system_prompt=(
                "You are a terse voice assistant. Answer in exactly one sentence. "
                "No preamble, no caveats. Avoid markdown or special characters."
            ),
        ),
        Persona(
            name="researcher",
            system_prompt=(
                "You are a research-oriented voice assistant. Cite specifics when you can, "
                "and ask one clarifying question if the query is ambiguous. "
                "Avoid markdown or special characters. Keep each response under five sentences."
            ),
        ),
    ]


class PersonaConfig(BaseModel):
    personas: list[Persona] = Field(default_factory=_default_personas)
    active: str = "default"


class ToolsConfig(BaseModel):
    enabled: bool = False
    allowed: list[str] = Field(default_factory=lambda: ["clock", "web_search"])
    web_search_provider: Literal["duckduckgo"] = "duckduckgo"


class ObsidianConfig(BaseModel):
    enabled: bool = False
    vault_root: Path = Path.home() / "Documents" / "Obsidian" / "local-tts"
    # If unset, topic-classification reuses the active ollama.model.
    topic_model: Optional[str] = None


class WakeWordConfig(BaseModel):
    enabled: bool = False
    model: str = "hey_jarvis"
    # Cosmetic alias shown in the header chip. The acoustic model still listens
    # for `model` above — this is label-only. Useful if you want the chip to
    # read "WAKE · HEY_MAC" while actually triggering on "hey jarvis".
    display_name: Optional[str] = None
    threshold: float = Field(0.5, ge=0.0, le=1.0)


class InputConfig(BaseModel):
    # "vad": always-on VAD-driven utterance detection (web default)
    # "wake_word": ignore audio until openWakeWord fires the configured word
    mode: Literal["vad", "wake_word"] = "vad"


class MemoryConfig(BaseModel):
    session_dir: Path = Path.home() / ".local-tts" / "sessions"
    keep_days: int = 30


class Config(BaseModel):
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    kokoro: KokoroConfig = Field(default_factory=KokoroConfig)
    whisper: WhisperConfig = Field(default_factory=WhisperConfig)
    vad: VADConfig = Field(default_factory=VADConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    obsidian: ObsidianConfig = Field(default_factory=ObsidianConfig)
    wakeword: WakeWordConfig = Field(default_factory=WakeWordConfig)
    input: InputConfig = Field(default_factory=InputConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)

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

        had_persona_section = "persona" in data
        cfg = cls(**data)

        # Legacy migration: if a user has `ollama.system_prompt` set in their
        # config.yaml (the pre-PersonaConfig schema) and no `persona` section,
        # override the seeded "default" persona's prompt with their value. The
        # other seed personas (concise, researcher) stay intact.
        if cfg.ollama.system_prompt and not had_persona_section:
            for p in cfg.persona.personas:
                if p.name == "default":
                    p.system_prompt = cfg.ollama.system_prompt
                    break

        return cfg
