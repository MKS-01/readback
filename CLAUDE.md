# readback — Project Context

An **offline article reader** with a browser UI. Paste a URL → fetch + extract the
article → optionally summarize it with a local LLM → synthesize the whole thing
with **CSM-1B** (Sesame, via `csm-mlx`) → play it in-browser or download the WAV.
All on-device on Apple Silicon. No cloud, no API keys.

**History:** this began as a real-time voice assistant (`local-tts`) and was
**pivoted to an article reader in v0.8.0**, then **renamed to `readback`**. The
entire live cascade — Parakeet STT, Smart-Turn, webrtcvad, mic capture, echo
gate, wake-word, personas, tools, Obsidian export — was removed. If you see those
referenced anywhere, it's stale: the current package is just
`llm/ reader/ tools/ tts/ web/`, and the reader server wires none of the
tools/persona/obsidian machinery.

**See [ARCHITECTURE.md](ARCHITECTURE.md)** for the system-level view (pipeline,
concurrency model, extension points). This file holds implementation notes,
gotchas, and exact knobs.

## Hardware

- Apple M5 Pro, 48 GB unified memory (primary target). No CUDA.
- **MLX/Metal (20-core GPU)** runs CSM-1B TTS; **Ollama** runs the summary LLM.
- **MLX is not multi-thread safe** — its default GPU stream binds to the thread
  that first touches the device, so `CsmEngine` owns a single-thread executor and
  runs all model work on it (see TTS section).

## Stack

- **Extraction**: `trafilatura` (URL → clean article text) + a browser-UA urllib
  fallback for sites that 403 the default agent.
- **LLM**: Ollama, default **`nemotron-3-nano:4b`** (`think=False` + `<think>`
  stripping). Used **only by Summary mode** (`LLMClient.oneshot`).
- **TTS**: **CSM-1B** (`senstella/csm-1b-mlx`, Sesame Conversational Speech Model)
  via **`csm-mlx`** on Metal, bf16, 24 kHz native. 2 built-in reading voices +
  clone-condition voices + optional LoRA fine-tuning. English-best.
- **Server**: FastAPI + WebSocket, single `/ws` endpoint.
- **Frontend**: React 18 + TypeScript + Vite + zustand; three.js point-cloud orb;
  custom audio player; dark "Ghost" theme. Built into
  `readback/web/static/dist/`; the server serves dist when present, else the
  legacy `static/index.html` bundle.

## Project Structure

```
readback/
├── pyproject.toml             # v0.8.0; csm-mlx (git dep) + ollama + trafilatura + fastapi
├── config.yaml                # user-editable: ollama / tts.csm / reader blocks
├── README.md                  # user-facing
├── ARCHITECTURE.md            # system-level view
├── finetune/                  # LoRA fine-tune pipeline (README + transcribe.py + data/)
├── voice/                     # reference clips for clone voices; *.wav gitignored
│                              # (exception: committed voice_kay_default.wav)
├── scripts/make_clone_voice.sh  # ffmpeg re-encode ANY audio → mono/24k/16-bit wav
│
└── readback/
    ├── __main__.py            # `readback` CLI: argparse, --auto-cert/--cert/--key, uvicorn boot
    ├── config.py              # Pydantic config: OllamaConfig / CsmTTSConfig (+ CsmVoicePrompt)
    │                          # / ReaderConfig; load() resolves clone wav + lora paths
    ├── llm/client.py          # LLMClient: oneshot() for summary; streaming/tools vestigial
    ├── reader/
    │   ├── extract.py         # fetch_article: trafilatura + UA fallback; TTS-prep scrub
    │   ├── summarize.py       # summarize_article: LLM oneshot → spoken explanation
    │   └── speak.py           # chunk_text + synthesize_article + _tidy_silence + write_wav
    ├── tts/
    │   ├── csm_engine.py      # CsmEngine (csm-mlx); single-thread MLX executor; _ref_for
    │   │                      # (built-in prompt / clone clip / empty-for-LoRA); voices_for
    │   └── synthesizer.py     # Synthesizer facade over CsmEngine
    ├── tools/                 # VESTIGIAL (clock, web_search) — not wired into the reader
    └── web/
        ├── server.py          # FastAPI app, /ws, read-job task + cancel, /audio serving
        ├── static/            # legacy vanilla-JS fallback + Vite dist/ output
        └── frontend/          # React app (vite build target = ../static/dist)
            └── src/
                ├── App.tsx, main.tsx
                ├── components/  # AudioPlayer, OrbContainer, Picker, icons
                ├── lib/         # ws.ts, brain.ts (three.js), prefs.ts
                └── state/       # zustand store
```

## Critical Implementation Notes

### Server pipeline (`web/server.py`)

- **Read jobs run as background tasks.** The `/ws` loop launches `_run_read_job`
  via `asyncio.create_task` and keeps receiving, so a `cancel` is handled
  mid-job. Cancel/disconnect flips `state["alive"] = False`, which silences sends
  and (via `should_stop`) aborts synthesis. One job per socket; a second `read`
  while busy returns an error.
- **Phases** stream as `phase` messages (`loading` → `fetching` → `summarizing` →
  `synthesizing`), then per-chunk `progress {done, total}`, then `done`.
- **`done` payload**: `{title, audio_url, duration_sec, word_count, mode, text}`.
  `text` is the spoken summary **only in Summary mode** (None in Full) — it feeds
  the client transcript panel; the full article isn't shipped back (it's on the
  source page).
- Models (`Synthesizer` + `LLMClient`) load lazily on first read via
  `ReaderModels.ensure_loaded` (downloads the CSM checkpoint the first time).

### Reader pipeline (`reader/`)

- **Extract** (`extract.py`): trafilatura first, browser-UA urllib fallback on
  empty/403. `_clean_for_tts` strips `https?://…`, `[12]` citation markers, and
  collapses whitespace. Missing title → slug from the URL tail.
- **Summarize** (`summarize.py`): `oneshot` with a spoken-explanation system
  prompt; truncates body to `reader.summary_max_chars` (default 16000). Returns
  the article text unchanged if the LLM produced nothing.
- **Chunk + synth** (`speak.py`):
  - `chunk_text` — paragraph-respecting, sentence-aware merge up to `_MAX_CHARS`
    (280); over-long single sentences split on commas; sub-`_MIN_CHARS` (8)
    fragments stitched onto neighbors.
  - `_tidy_silence` — ⚠ **this is what removes the halting feel.** CSM, conditioned
    on the casual/disfluent Sesame prompt, emits long mid-utterance pauses;
    `_tidy_silence` trims leading/trailing silence (−40 dB threshold) and caps any
    internal silent run to `max_pause_ms` (300). Model-agnostic post-processing.
  - `synthesize_article` — synth each chunk, tidy, join with `reader.gap_sec`
    (0.18 s) gaps; `progress`/`should_stop` hooks; a chunk that throws is skipped,
    not fatal.

### TTS — CSM-1B (`tts/csm_engine.py`, `tts/synthesizer.py`)

- **Engine: `csm-mlx`** (`senstella/csm-1b-mlx`, `ckpt.safetensors`). float32 @
  24 kHz, cast to **bf16** by default (`cfg.precision`: `bf16`/`fp16`/`fp32`).
  Offline, so `fp32` is viable for max quality.
- **MLX single-thread:** `ThreadPoolExecutor(max_workers=1)` owns load + all
  synth. `_impl` methods run ON that thread and must never re-submit. Never call
  `mx` ops or the engine's `_impl` from another thread.
- **`_ref_for(voice)` — the voice selector**, cached per voice:
  1. `cfg.lora_path` set → returns **`[]`** (empty context); the fine-tuned voice
     lives in the adapter (per the csm-mlx FINETUNING preset).
  2. voice is a `cfg.voices` clone → builds the `Segment` from the **local clip +
     its `ref_text`**.
  3. otherwise → built-in reading prompt downloaded from `sesame/csm-1b`
     (`read_speech_a/b.wav` + hardcoded transcripts).
  `ref_max_sec` (None = full clip) trims the reference audio AND its transcript
  together — a mismatched (audio, text) pair garbles the voice.
- **LoRA** (`_load_impl`): when `cfg.lora_path` is set, `csm_mlx.load_adapters`
  is applied over the base weights after the dtype cast.
- **Voices**: `SUPPORTED_VOICES` = 2 built-ins (`conversational_a` ★ female,
  `conversational_b` male). `voices_for(cfg)` = built-ins + `cfg.voices` clones;
  used by both the engine's `supported_voices` and the server's picker.
  `swap_voice` validates against `voices_for`. `temperature` tunes **delivery**
  (lower = composed/measured, higher = livelier); **below ~0.55 with a short
  (<5 s) reference the clone destabilizes** (rambles/repeats).
- **`synthesize_stream`** exists (csm-mlx `stream_generate`) but the reader uses
  batch `synthesize` (offline — no streaming benefit).

### Voice cloning & fine-tuning

- **Clone-condition** (`tts.csm.voices`, `CsmVoicePrompt`): a local clip's timbre +
  tone are reproduced. Fields: `name`, `label`, `wav` (resolved relative to
  `config.yaml`), `ref_text` (the clip's **exact** transcript), `speaker`. The
  bundled config ships a sample `kay` voice (`voice/voice_kay_default.wav`, the
  one committed-past-gitignore reference clip).
- **The reusable procedure lives in `.claude/skills/csm-voice`** — clone, tune
  delivery, or LoRA fine-tune. Read it before any voice work.
- **LoRA fine-tune** pipeline in `finetune/` (`README.md`): `transcribe.py` →
  `csm-mlx finetune convert` → `csm-mlx finetune lora sft` → set `tts.csm.lora_path`.
  Tuned for M5/48 GB (batch 1 + grad-accum + checkpointing; full fine-tune is
  Mac-Studio-class RAM).

### Config (`config.py`)

- `OllamaConfig{model, host, system_prompt}` — `system_prompt`
  (`DEFAULT_PERSONA_PROMPT`) is **vestigial** (summary uses its own prompt via
  `oneshot`; nothing reads `system_prompt` in the reader path).
- `CsmTTSConfig{precision, speaker, temperature, top_k, max_audio_length_ms,
  ref_max_sec, voices, lora_path, …}`. `speed`, `model`, `watermark`,
  `context_turns` are **inert** (kept for back-compat; csm-mlx has no equivalents
  / the checkpoint is fixed in the engine).
- `ReaderConfig{output_dir, default_mode, gap_sec, summary_max_chars}`.
- `Config.load()` resolves clone `wav` paths and `lora_path` relative to the
  config file's directory.

### LLM (`llm/client.py`)

- The reader uses only **`oneshot(system, user)`** — one non-streaming Ollama
  `chat`, `think=False`, `temperature=0.4`, `<think>` stripped.
- `_ThinkStripper` removes `<think>…</think>` across chunk boundaries.
- `stream_response` / `_stream_tokens_with_tools` / the `tools` arg are
  **vestigial** voice-assistant code — unused by the reader.

### Frontend (`web/frontend/`)

- Single `App.tsx` orchestrator. The three.js orb (`brain.ts`) and WS client
  (`ws.ts`) are singletons **outside** the React tree pushing into the zustand
  store, so re-renders never tear down the socket.
- **Custom `AudioPlayer`** — hidden `<audio>` drives a themed UI (circular
  play/pause, seek `<input range>`, tabular times); play/pause flips the orb phase.
- **Busy state** — while a read runs, input/controls collapse and a hero-orb view
  shows the phase message + progress bar (indeterminate until per-chunk progress
  arrives) + **Cancel**.
- **Summary transcript** — `Show transcript` toggle + `Copy` (from `done.text`),
  Summary mode only.
- Single dark **Ghost** theme. Prefs key `localStorage["readback.prefs.v12"]`
  (theme, voice, mode).

## Things that look like bugs but aren't

- **First synth is slow.** One-time CSM graph warm-up + ~6 GB checkpoint download
  on first ever run; `load()` pre-warms but the first real synth still pays some
  compile cost.
- **Summary mode has no first-token streaming.** Summary is a single `oneshot`
  call — the whole summary is produced, then synthesized. (Full mode skips the
  LLM entirely.)
- **Speed has no effect.** `tts.csm.speed` is inert — CSM has no speed control.
- **Clone sounds garbled.** Almost always a `ref_text` that doesn't match the
  clip, or a too-short reference at low temperature. Fix the transcript / use a
  5–8 s clip / raise temperature toward 0.6–0.8.
- **`<think>` leaks only on qwen3.** qwen3 ignores `think=False` and emits
  untagged reasoning; the default `nemotron-3-nano:4b` is clean.

## Known dead/vestigial code (cleanup candidates — see TODO.md)

- `readback/tools/` (`clock`, `web_search`) + the tool-calling plumbing in
  `llm/client.py` — unused by the reader.
- `readback/web/static/` legacy vanilla-JS bundle (`index.html`, `app.js`, …) —
  superseded by the React `dist/`.
- Inert `CsmTTSConfig` fields (`speed`, `model`, `watermark`, `context_turns`) and
  the vestigial `OllamaConfig.system_prompt`.
- Generated WAVs in `~/.readback/reader/` grow unbounded (no rotation yet).

## Install & verification

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .                          # csm-mlx is a git dep (allow-direct-references)
cd readback/web/frontend && npm install && npm run build && cd ../../..
readback                                  # http://127.0.0.1:8000   (or: python -m readback)
```

Smoke test: paste an article URL → Full mode → player appears, audio plays,
download works. Summary mode → transcript toggle shows the spoken summary. Voice
work: `Synthesizer(Config.load().tts).synthesize("…")` from a Python REPL.

## Version

Current: **v0.8.0** — offline article reader; CSM-1B via csm-mlx; clone-condition
voices + LoRA fine-tune scaffold; renamed `local-tts` → `readback`. Set in
`pyproject.toml`, `readback/__init__.py`, `web/frontend/package.json`. Bump all
three when releasing.
