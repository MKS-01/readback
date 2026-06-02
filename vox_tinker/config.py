from pathlib import Path
from typing import Optional, Literal

import yaml
from pydantic import BaseModel, Field


DEFAULT_PERSONA_PROMPT = (
    "You are a sharp, tech-savvy voice assistant with an easygoing, friendly streak. "
    "You know your way around software, hardware, gadgets, and the wider tech world, "
    "and you explain things in plain language, reaching for a quick everyday analogy "
    "when a concept is tricky. Be warm and conversational with a light touch of dry "
    "humor, never robotic or fawning. Get to the point first, then add a little useful "
    "context if it helps. When something is uncertain or outside what you know, say so "
    "honestly instead of bluffing, and ask a quick clarifying question if the request "
    "is ambiguous. Since this is read aloud, speak naturally in complete sentences and "
    "avoid bullet points, markdown, or special characters. Keep responses to about "
    "three or four sentences unless asked for more depth."
)


class OllamaConfig(BaseModel):
    model: str = "nemotron-3-nano:4b"
    host: str = "http://localhost:11434"
    # Legacy: kept Optional for backward-compatibility with config.yaml files
    # that set `ollama.system_prompt`. At Config.load() time we promote it to
    # the "default" persona if no `persona` section is present.
    system_prompt: Optional[str] = None


class CloneVoiceConfig(BaseModel):
    # A reference-audio cloned voice. Selectable in the UI as id "clone:<name>".
    # Cloning needs the Base Qwen3-TTS checkpoint (see QwenTTSConfig.base_model);
    # ref_text is the transcript of the clip IN ITS OWN LANGUAGE (auto-filled via
    # the multilingual Whisper engine when left None, e.g. a Hindi clip → Hindi
    # transcript). The cloned timbre then speaks whatever (English) text we send.
    name: str
    label: Optional[str] = None          # picker label; defaults to name
    wav: str                             # path to the reference wav (tilde-expanded)
    ref_text: Optional[str] = None       # transcript; auto-transcribed if None
    ref_lang: Optional[str] = None       # ISO code for transcription (None = autodetect)
    # Emotion/style hint applied when speaking in this clone ("smiling, cheerful",
    # "angry", "sad, soft", "excited, fast"). Shapes HOW it speaks; wav sets WHO.
    instruct: Optional[str] = None
    # Per-clone tuning (fall back to the engine defaults when None):
    #   speed       — <1.0 slower / >1.0 faster (1.0 = natural)
    #   temperature — higher = more expressive/varied, lower = flatter/steadier
    speed: Optional[float] = None
    temperature: Optional[float] = None


class QwenTTSConfig(BaseModel):
    # Qwen3-TTS via mlx-audio (MLX/Metal, 24 kHz). CustomVoice = preset speakers;
    # Base = reference-audio voice cloning. One model is loaded at a time: picking
    # a clone reloads the Base model, picking a preset reloads CustomVoice.
    model: str = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"
    base_model: str = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16"
    speaker: str = "ryan"                # active voice; may hold "clone:<name>"
    speed: float = 1.0
    # Optional voice-design instruction (e.g. "excited, fast"); None = neutral.
    instruct: Optional[str] = None
    clones: list[CloneVoiceConfig] = Field(default_factory=list)


class TTSConfig(BaseModel):
    # Kokoro was removed; Qwen3-TTS is the sole engine for now. Kept as a single
    # "engine" enum so re-adding Kokoro later is a config + factory change only.
    engine: Literal["qwen"] = "qwen"
    qwen: QwenTTSConfig = Field(default_factory=QwenTTSConfig)


class WhisperConfig(BaseModel):
    model: str = "medium"
    compute_type: Literal["int8", "float16", "float32"] = "int8"
    beam_size: int = 5


class ParakeetConfig(BaseModel):
    # HuggingFace id resolved by parakeet-mlx's from_pretrained. Streaming-capable
    # NVIDIA Parakeet (MLX/Metal). v2 = English; v3 = 25 langs.
    model: str = "mlx-community/parakeet-tdt-0.6b-v2"
    # transcribe_stream attention context (left, right) in mel frames.
    context_left: int = 256
    context_right: int = 256
    # Streaming feeds add_audio in blocks of this size. The mic delivers 30 ms
    # frames, but Parakeet's encoder underflows on sub-~100 ms adds — we buffer
    # to this many ms before each step. ~320 ms balances caption latency vs
    # decode accuracy (smaller blocks degrade word boundaries).
    stream_chunk_ms: int = 320


class STTConfig(BaseModel):
    # "parakeet": NVIDIA Parakeet via MLX (default, streaming-capable).
    # "whisper":  faster-whisper (batch only). Both stay selectable at runtime.
    engine: Literal["parakeet", "whisper"] = "parakeet"
    whisper: WhisperConfig = Field(default_factory=WhisperConfig)
    parakeet: ParakeetConfig = Field(default_factory=ParakeetConfig)


class VADConfig(BaseModel):
    aggressiveness: int = Field(2, ge=0, le=3)


class TurnConfig(BaseModel):
    # Smart-Turn v3 semantic end-of-turn detection layered on top of the
    # webrtcvad pause-gate. When the model can't be loaded (offline / missing
    # deps), the pipeline gracefully falls back to finalizing on VAD pause alone.
    enabled: bool = True
    repo_id: str = "pipecat-ai/smart-turn-v3"
    model_file: str = "smart-turn-v3.2-cpu.onnx"
    # P(turn complete) >= threshold ends the turn; else keep listening.
    threshold: float = Field(0.5, ge=0.0, le=1.0)
    # Safety cap: force end-of-turn after this much continuous silence even if
    # the model keeps saying "incomplete" (prevents hanging on a trailing pause).
    # Kept short so a mis-firing Smart-Turn can't make input feel unresponsive —
    # the common case (clear sentence end) still finalizes at ~750ms.
    max_wait_sec: float = 3.0


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
                "You are a rigorous research assistant. Lead with the direct answer, "
                "then give the key reasoning or evidence behind it in a sentence or two. "
                "Cite specifics — names, dates, numbers, or sources — whenever you can, "
                "and clearly separate established fact from your own inference or estimate. "
                "When something is uncertain, contested, or outside what you know, say so "
                "plainly instead of guessing. If the query is ambiguous, ask one focused "
                "clarifying question before answering. Stay neutral and precise, define a "
                "term the first time you use it, and end by offering a useful next step or "
                "angle to explore. Since this is read aloud, avoid markdown, numbered lists, "
                "or special characters, and keep each answer to a few clear sentences unless "
                "asked to go deeper."
            ),
        ),
        Persona(
            name="chef",
            system_prompt=(
                "You are a warm home cook. When asked for a recipe or what to cook, "
                "default to simple everyday Indian home cooking with classic flavors "
                "(cumin, turmeric, garam masala, ginger and garlic), unless the user "
                "asks for a different cuisine. Lean vegetarian or egg-based by default "
                "and only suggest meat or fish when the user asks for it. Vary your "
                "suggestions across the meal — think breakfast and snacks like aloo "
                "paratha, poha, masala omelette, or upma; light mains like dal, jeera "
                "rice, or a sabzi; and drinks like masala chai or a cold brew — rather "
                "than always reaching for a heavy curry. Match the time of day and "
                "effort the user hints at, and ask a quick question if it is unclear "
                "(veg or non-veg, breakfast or dinner). Give the dish name, then the "
                "ingredients and steps in a natural spoken order, briefly. Since this "
                "is read aloud, avoid markdown, numbered lists, or special characters. "
                "Keep it to a few sentences and offer one handy tip at the end."
            ),
        ),
        Persona(
            name="professor",
            system_prompt=(
                "You are Professor Miss Phd, a witty woman with a PhD in artificial "
                "intelligence and a working AI researcher. Your field is AI and machine "
                "learning — never anthropology or any other field. Your name is Miss "
                "Phd. Refer to yourself with she/her. Introduce yourself by name ONLY "
                "once, in your very first reply of a conversation, as a single short "
                "playful line such as: \"Hi, I'm Professor Miss Phd, an AI researcher "
                "with a doctorate in artificial intelligence and your slightly "
                "over-caffeinated guide for today.\" If the conversation already has "
                "earlier turns, do NOT introduce yourself or greet at all — just answer "
                "the question directly. Never repeat your name or introduction after "
                "the first reply. You explain things clearly from first principles, building "
                "intuition with a simple analogy or concrete example before any "
                "detail, and you sprinkle in light, dry humor and the occasional pun "
                "without overdoing it. Define a term the first time you use it. Stay "
                "accurate and say so plainly when something is uncertain or unknown "
                "rather than guessing. Keep a warm, encouraging lecturer's tone and "
                "end by checking understanding or suggesting what to explore next. "
                "Since this is read aloud, avoid markdown, numbered lists, or special "
                "characters, and keep each answer to a few clear sentences unless "
                "asked to go deeper."
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
    vault_root: Path = Path.home() / "Documents" / "Obsidian" / "vox-tinker"
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
    session_dir: Path = Path.home() / ".vox-tinker" / "sessions"


class Config(BaseModel):
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    vad: VADConfig = Field(default_factory=VADConfig)
    turn: TurnConfig = Field(default_factory=TurnConfig)
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

        # Legacy migration: pre-dual-engine config.yaml files had a top-level
        # `whisper:` block. Capture it before the unknown-key filter drops it,
        # then fold it into `stt.whisper` if no explicit `stt:` section exists.
        # The engine default stays "parakeet" — we only preserve the user's
        # Whisper model/beam choice for when they switch back to Whisper.
        legacy_whisper = data.get("whisper")
        had_stt_section = "stt" in data

        # Drop unknown top-level keys so old config.yaml files with cli-only
        # sections (audio, input) don't cause validation errors.
        known = cls.model_fields.keys()
        data = {k: v for k, v in data.items() if k in known}

        had_persona_section = "persona" in data
        cfg = cls(**data)

        if isinstance(legacy_whisper, dict) and not had_stt_section:
            cfg.stt.whisper = WhisperConfig(**legacy_whisper)

        # Legacy migration: if a user has `ollama.system_prompt` set in their
        # config.yaml (the pre-PersonaConfig schema) and no `persona` section,
        # override the seeded "default" persona's prompt with their value. The
        # other seed personas (concise, researcher) stay intact.
        if cfg.ollama.system_prompt and not had_persona_section:
            for p in cfg.persona.personas:
                if p.name == "default":
                    p.system_prompt = cfg.ollama.system_prompt
                    break

        # Resolve clone wav paths so they don't depend on the launch CWD. A
        # relative path (e.g. "voice/intro.wav") is anchored to the config
        # file's directory; absolute and "~"-paths are left as the user wrote
        # them. The engine reads cfg.tts.qwen.clones[].wav verbatim afterward.
        base_dir = path.resolve().parent
        for c in cfg.tts.qwen.clones:
            wav = Path(c.wav).expanduser()
            if not wav.is_absolute():
                wav = base_dir / wav
            c.wav = str(wav)

        return cfg
