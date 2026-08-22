from pathlib import Path
from typing import Optional, Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class LLMConfig(BaseModel):
    # ONE model for both jobs: Summary mode (spoken explanation via
    # LLMClient.oneshot) + title generation via mlx-lm, AND image / book-scan OCR
    # via mlx-vlm. The default is a VLM (`model_type: qwen3_5` carries a
    # `vision_config`, and mlx-vlm ships a `qwen3_5` handler), so a second OCR
    # model would be redundant — the separate `ocr:` block was removed.
    # ⚠ Switching this to a text-only model disables image/book reads.
    model: str = "mlx-community/Qwen3.5-9B-4bit"


class CsmVoicePrompt(BaseModel):
    """A custom reference voice for CSM (clone-condition). CSM conditions every
    sentence on a reference (audio + its exact transcript); the clip's timbre AND
    prosody set the output's voice. Add clips under `tts.csm.voices`.

    `wav` is resolved relative to the config file's directory (so `voice/x.wav`
    is portable). `ref_text` MUST be the clip's exact transcript — a mismatched
    (audio, text) pair garbles the voice. `speaker` is the CSM speaker slot."""
    name: str                 # picker id (also the value stored in prefs)
    label: str                # UI label
    wav: Path                 # reference clip (mono 24 kHz wav)
    ref_text: str             # exact transcript of the clip
    speaker: int = 0          # CSM speaker slot


class CsmTTSConfig(BaseModel):
    # CSM-1B (Sesame Conversational Speech Model) via csm-mlx (senstella/csm-mlx,
    # MLX/Metal, 24 kHz) as of v0.7.x. Two voices map to CSM speaker IDs
    # (conversational_a → 0, conversational_b → 1); we synth with empty context so
    # there's no per-sentence reference-prompt prefill. The checkpoint
    # (senstella/csm-1b-mlx) is fixed in the engine.
    # Inference precision: bf16 ~halves F32 compute, native on Apple Silicon (no
    # per-op dequant), keeps the voice clean. "fp32" = full precision (slow, RTF
    # ~1.4); "fp16" = slightly faster, narrower range.
    precision: Literal["bf16", "fp16", "fp32"] = "bf16"
    speaker: str = "conversational_a"    # active voice (→ CSM speaker id)
    # Sampler. Lower temperature = steadier/more consistent voice (no reference
    # clip to pin timbre, so this is the main consistency knob).
    temperature: float = 0.7
    top_k: int = 50
    # Per-sentence generation cap (ms). Bounds runaway generation if EOS never
    # fires; kept under CSM's 2048-token budget. 20 s is ample for one sentence.
    # ⚠ Raised 20000 → 30000: this is a runaway-generation SAFETY bound, but at
    # 20 s it was being hit by ordinary chunks and clipping them mid-sentence —
    # a 370-char chunk measured 19.84 s of audio against the cap, where the same
    # text yields 21.84 s given room. Chunks run up to _MAX_CHARS (400), so the
    # bound has to clear that. Costs nothing: generation stops at EOS, so a
    # higher ceiling is never reached by a well-behaved chunk (measured
    # identical wall time at 20 s vs 60 s caps).
    max_audio_length_ms: int = 30000
    # Voice reference prompt cap (seconds). CSM conditions every sentence on the
    # built-in Sesame prompt clip for the active voice — this is what keeps the
    # voice GOOD and CONSISTENT (empty context drifts + degrades). None/0 = full
    # clip (~10 s; measured RTF ~0.8 on M5, still realtime). Lower it only if you
    # need more headroom — trims the clip AND its transcript together (a
    # mismatched pair garbles the voice).
    ref_max_sec: Optional[float] = None
    # How many chunks to synthesize in ONE CSM frame loop. ⚠ The single biggest
    # speed knob. CSM's per-frame cost is launch-latency-bound, not compute-bound
    # (1 backbone + 31 sequential decoder steps on a 1B model), so the GPU is
    # mostly idle at batch 1. Measured on M5 Pro — ms/frame → audio per
    # wall-second: 1 → 51.6 ms / 1.55 s · 2 → 80.5 / 1.99 · 4 → 82.1 / 3.90 ·
    # 8 → 84.8 / 7.55. Costs KV cache proportional to the batch (trivial for a
    # 1B model). 1 = the old sequential path.
    batch_size: int = 8
    # Custom clone-condition voices (timbre + tone from a local clip). Each
    # appears in the voice picker alongside the two built-in reading voices.
    voices: list[CsmVoicePrompt] = Field(default_factory=list)
    # Optional LoRA adapter from a `csm-mlx finetune lora` run — a directory with
    # adapters.safetensors + adapter_config.json (resolved relative to this config
    # file). When set, the engine loads it over the base weights and follows the
    # FINETUNING preset: generate with EMPTY context (the fine-tuned voice lives in
    # the adapter, not a reference clip). None = base model + read-speech prompt.
    lora_path: Optional[Path] = None


class TTSConfig(BaseModel):
    # CSM-1B is the sole TTS engine (Qwen3-TTS was replaced). Kept as a single
    # "engine" enum so a future engine (e.g. a MisoTTS-8B MLX port) is a config +
    # factory change only.
    engine: Literal["csm"] = "csm"
    csm: CsmTTSConfig = Field(default_factory=CsmTTSConfig)

    @property
    def active(self) -> CsmTTSConfig:
        """The active engine's sub-config. Lets the server stay engine-agnostic
        instead of reaching into a named block."""
        return self.csm


class FeedSource(BaseModel):
    """One site in `reader.feeds` — the URL of its blog index (or its feed).

    `name` is optional: the picks list falls back to the host name. Written in
    YAML either as a bare URL string or as a `{url, name}` mapping; the
    validator below accepts both so the common case stays a one-line list."""
    url: str
    name: Optional[str] = None

    @classmethod
    def _coerce(cls, v):
        return cls(url=v) if isinstance(v, str) else v


class ReaderConfig(BaseModel):
    # Offline article reader (project pivot, v0.8.0). Generated WAVs are written
    # here and served for playback + download. Default keeps audio alongside the
    # library DB (see library_db) in a sibling `readback-audio-db/` folder next to
    # the repo — visible + back-up-able, not a hidden ~/.readback dir that's easy
    # to delete by accident. Relative paths resolve against config.yaml's dir.
    output_dir: Path = Path("../readback-audio-db/audio")
    default_mode: Literal["full", "summary"] = "full"
    gap_sec: float = 0.18                 # base silence between (trimmed) chunks;
                                          # scaled per join by speak._gap_for —
                                          # paragraph ends breathe, mid-paragraph
                                          # splits carry on
    # Cap article text for a single LLM pass before map-reducing. Qwen3.5-9B has
    # a 262K-token context, so 60K chars (~15K tokens) single-passes the vast
    # majority of articles instead of map-reducing.
    summary_max_chars: int = 60000
    # SQLite library of past reads (powers the web dashboard). One file, stdlib
    # sqlite3. Default sits in the sibling `readback-audio-db/` folder next to the
    # repo; relative paths resolve against config.yaml's dir.
    library_db: Path = Path("../readback-audio-db/library.db")

    # Sites whose newest posts are offered as picks the moment the CLI opens —
    # pick one by number and it's summarized immediately, no URL to paste. Each
    # entry is a blog INDEX url (a feed url works too); readback finds the RSS/
    # Atom feed itself, and scrapes the index when a site has no feed. Empty
    # list = no picks section at all.
    feeds: list[FeedSource] = Field(default_factory=list)
    feed_picks: int = 3          # how many picks to show (1–9; keyed 1..N in the CLI)
    feed_ttl_sec: float = 900.0  # cache window before re-crawling (/feed forces it)

    @field_validator("feeds", mode="before")
    @classmethod
    def _accept_bare_urls(cls, v):
        """`feeds: ["https://…"]` is as valid as `[{url: …, name: …}]`."""
        if isinstance(v, list):
            return [FeedSource._coerce(item) for item in v]
        return v


class Config(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    reader: ReaderConfig = Field(default_factory=ReaderConfig)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        if path is None:
            path = Path("config.yaml")
        # `config.yaml` is the user's own file and is gitignored, so a fresh
        # clone (or a run before setup.sh) has only the checked-in template.
        # Fall back to it rather than to bare defaults — otherwise the shipped
        # voice, feed list, and reader paths silently disappear.
        if not path.exists():
            example = path.parent / "config.example.yaml"
            if not example.exists():
                return cls()
            path = example
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}

        # Migrate old `ollama:` key → `llm:` (v3.8.0 renamed the section).
        if "ollama" in data and "llm" not in data:
            data["llm"] = data.pop("ollama")

        # Old configs may still carry a separate OCR model (`ocr.model`, or the
        # even older `llm.vision_model`). OCR now runs on `llm.model`, so both are
        # simply ignored — `llm.vision_model` by pydantic's extra="ignore", the
        # `ocr:` block by the unknown-key drop below.

        # Drop unknown top-level keys so older config.yaml files with removed
        # sections don't cause validation errors.
        known = cls.model_fields.keys()
        data = {k: v for k, v in data.items() if k in known}

        cfg = cls(**data)
        base = path.resolve().parent

        # Resolve clone-voice clip paths + the LoRA adapter dir relative to the
        # config file's directory (so `voice/x.wav` / `finetune/runs/v1` are
        # portable). Absolute / ~ paths are left as written.
        for v in cfg.tts.csm.voices:
            wav = Path(str(v.wav)).expanduser()
            v.wav = wav if wav.is_absolute() else (base / wav)
        if cfg.tts.csm.lora_path is not None:
            lp = Path(str(cfg.tts.csm.lora_path)).expanduser()
            cfg.tts.csm.lora_path = lp if lp.is_absolute() else (base / lp)

        # Reader paths: ~ expands; a relative path resolves against config.yaml's
        # dir, then is normalized (so a `../` default becomes a clean absolute
        # path — what gets stored in the DB's audio_path).
        for attr in ("output_dir", "library_db"):
            p = Path(str(getattr(cfg.reader, attr))).expanduser()
            setattr(cfg.reader, attr, (p if p.is_absolute() else (base / p)).resolve())

        return cfg
