# readback — Project Context

An **offline article reader**, terminal-first. Paste a URL → fetch + extract the
article → optionally summarize it with a local LLM → synthesize the whole thing
with **CSM-1B** (Sesame, via `csm-mlx`) → play it in the terminal via `afplay`.
All on-device on Apple Silicon. No cloud, no API keys.

**History:** this began as a real-time voice assistant (`local-tts`) and was
**pivoted to an article reader in v0.8.0**, then **renamed to `readback`**. The
entire live cascade — Parakeet STT, Smart-Turn, webrtcvad, mic capture, echo
gate, wake-word, personas, tools, Obsidian export — was removed. If you see those
referenced anywhere, it's stale: the current package is just
`llm/ pipeline/ tts/ server/`, and the server wires none of the
tools/persona/obsidian machinery (the `tools/` module and the streaming/
tool-calling LLM plumbing were removed in the v0.8.0 cleanup).

**See [ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the system-level view (pipeline,
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
- **LLM**: Ollama, default **`gemma4:26b`** (`think=False` + `<think>`
  stripping). Used **only by Summary mode** (`LLMClient.oneshot`).
- **TTS**: **CSM-1B** (`senstella/csm-1b-mlx`, Sesame Conversational Speech Model)
  via **`csm-mlx`** on Metal, bf16, 24 kHz native. 2 built-in reading voices +
  clone-condition voices + optional LoRA fine-tuning. English-best.
- **Server**: FastAPI + WebSocket, single `/ws` endpoint. No browser UI — the
  server is a pure backend for the CLI client.
- **Terminal CLI**: Bun + TypeScript + Ink (React for CLIs) in `src/cli/` — the sole
  client of the `/ws` protocol; `afplay` playback, macOS-only.

## Project Structure

```
readback/
├── pyproject.toml             # v2.0.0; csm-mlx (git dep) + ollama + trafilatura + fastapi
├── config.yaml                # user-editable: ollama / tts.csm / reader blocks (cwd-resolved)
├── README.md                  # user-facing (GitHub landing; stays at root)
├── docs/
│   ├── ARCHITECTURE.md        # system-level view
│   ├── SETUP.md               # end-to-end setup guide
│   ├── PLAN.md                # planning history (newest entry on top)
│   └── media/                 # README screenshots + sample WAV
│
└── src/
    ├── finetune/              # LoRA fine-tune pipeline (README + transcribe.py + data/)
    ├── voice/                 # reference clips for clone voices; *.wav gitignored
    │                          # (exceptions: committed voice_kay_default.wav +
    │                          # voice_kay_long.wav, the active kay reference)
    ├── cli/                   # terminal client (Bun + Ink); sole /ws client
    │   ├── package.json       # readback-cli 2.0.0; ink + ink-text-input
    │   ├── install.sh         # one-command build: bun compile → ~/.local/bin/readback-cli
    │   └── src/               # index.tsx (boot + resize repaint), app.tsx (screen
    │                          # switch), theme.ts (Ghost + BLUE accent),
    │                          # server.ts (spawn), ws.ts, player.ts (afplay + seek),
    │                          # prefs.ts, components/{Header,UrlInput,StatusLine,
    │                          # BusyView,PlayerView,ModelList}.tsx
    └── readback/              # python package (src layout; wheel packages src/readback)
        ├── __main__.py        # `readback` CLI: argparse --host/--port/--model/--config, uvicorn boot
        ├── config.py          # Pydantic config: OllamaConfig / CsmTTSConfig (+ CsmVoicePrompt)
        │                      # / ReaderConfig; load() resolves clone wav + lora paths
        ├── llm/
        │   ├── client.py      # LLMClient.oneshot() for summary + the <think> stripper
        │   └── models.py      # Ollama model listing + RAM-fit verdict (GET /api/models)
        ├── pipeline/
        │   ├── extract.py     # fetch_article: trafilatura + UA fallback; TTS-prep scrub
        │   ├── summarize.py   # summarize_article: LLM oneshot → spoken explanation
        │   └── speak.py       # chunk_text + synthesize_article + _tidy_silence + write_wav
        ├── tts/
        │   ├── csm_engine.py  # CsmEngine (csm-mlx); single-thread MLX executor; _ref_for
        │   │                  # (built-in prompt / clone clip / empty-for-LoRA); voices_for
        │   └── synthesizer.py # Synthesizer facade over CsmEngine
        └── server/
            └── server.py      # FastAPI app, /ws, read-job task + cancel, /audio serving
```

## Critical Implementation Notes

### Server pipeline (`server/server.py`)

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
- No browser UI — `GET /` returns 404. The server is a pure WS/API backend.

### Pipeline (`pipeline/`)

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
  bundled config ships a sample `kay` voice. Its active reference is
  `src/voice/voice_kay_long.wav` — an 11 s clip CSM-bootstrapped (2026-06-10) from
  the original 3.2 s `voice_kay_default.wav` to fix short-ref instability; both
  are committed past the gitignore.
- **The reusable procedure lives in `.claude/skills/csm-voice`** — clone, tune
  delivery, or LoRA fine-tune. Read it before any voice work.
- **LoRA fine-tune** pipeline in `src/finetune/` (`README.md`): `transcribe.py` →
  `csm-mlx finetune convert` → `csm-mlx finetune lora sft` → set `tts.csm.lora_path`.
  Tuned for M5/48 GB (batch 1 + grad-accum + checkpointing; full fine-tune is
  Mac-Studio-class RAM).

### Config (`config.py`)

- `OllamaConfig{model, host}` — summary uses its own prompt via `oneshot`.
- `CsmTTSConfig{precision, speaker, temperature, top_k, max_audio_length_ms,
  ref_max_sec, voices, lora_path}`. The checkpoint (`senstella/csm-1b-mlx`) is
  fixed in the engine.
- `ReaderConfig{output_dir, default_mode, gap_sec, summary_max_chars}`.
- `Config.load()` resolves clone `wav` paths and `lora_path` relative to the
  config file's directory.

### LLM (`llm/client.py`)

- The reader uses only **`oneshot(system, user)`** — one non-streaming Ollama
  `chat`, `think=False`, `temperature=0.4`, `<think>` stripped.
- `_ThinkStripper` removes `<think>…</think>` across chunk boundaries. The
  streaming/tool-calling methods and the `tools/` module were removed in the
  v0.8.0 cleanup.
- `llm/models.py` (`GET /api/models` + the `read` message's `model` field):
  lists installed Ollama models with a RAM-fit verdict (need ≈ size×1.2+1 GiB;
  good ≤50% / tight ≤75% of total RAM via `sysctl hw.memsize`) and recommends
  the largest good-fit chat model. A per-read `model` mutates
  `cfg.ollama.model` in place (process-wide, like `swap_voice`; **not** written
  back to `config.yaml`) — `oneshot()` picks it up per call, no reload.

### CLI (`src/cli/`)

- **The `/ws` client** — Bun + Ink, same protocol as the server, zero
  Python changes. `ws.ts` and `player.ts` are module singletons outside the
  React tree (so re-renders never tear down the socket/player). Flags:
  `--host` (127.0.0.1), `--port` (8000), `--no-spawn`.
- **Auto-spawn lifecycle** (`server.ts`): health-check `GET /api/config`; if no
  server, spawn `readback` (prefers `.venv/bin/readback`, cwd = repo root so
  `config.yaml` resolves), wait up to 60 s; on exit kill it **only if we spawned
  it** — SIGTERM, then **SIGKILL after 1.5 s** because uvicorn's graceful
  shutdown can hang on the open websocket. A SIGKILL of the CLI itself orphans
  the spawned server.
- **Ink screen model** (`app.tsx`): `useReducer` switches one mounted screen
  (`input` | `busy` | `player`), so key handlers only land on the active screen.
  Slash commands: `/voice`, `/mode`, `/model` (lists local Ollama models via
  `GET /api/models` with a RAM-fit verdict + summary recommendation, switches
  the summary LLM per-read), `/help`, `/quit`; esc cancels a read.
- **Playback = `afplay`** (macOS-only): pause/resume via **SIGSTOP/SIGCONT**;
  always SIGCONT before SIGTERM (a SIGSTOPped process can't handle SIGTERM).
  Caveats: pause flushes ~0.5 s of buffer, elapsed time is wall-clock-tracked.
  Plays the local WAV in `~/.readback/reader/` when present, else downloads
  from `/audio`.
- **Seek (←/→ ±5 s)** despite afplay having no transport: `player.ts` parses
  the WAV's RIFF chunks, slices the PCM data at the target byte offset into
  `$TMPDIR/readback-seek-<pid>.wav`, and relaunches afplay there. Rapid
  presses debounce (180 ms) into one jump; a generation counter invalidates
  superseded exits. Seeking from paused/finished resumes playback.
- **Synced transcript** (`PlayerView`): Summary-mode transcript highlights
  word by word in blue. No word timestamps exist — each word gets duration
  proportional to its char count. ⚠ The component wraps text **itself** (one
  `<Text>` per line): ink's `wrap="wrap"` drops ANSI state when a color
  boundary crosses a line break.
- **Resize repaint** (`index.tsx`): a `prependListener("resize")` runs before
  ink's own resize handler — `ink.clear()` + screen wipe so ink repaints on a
  blank slate. Without it, re-wrapped old frames make ink erase the wrong
  number of lines and stale banners stack up. (Alt-screen was tried and is
  glitchier in Warp; don't reintroduce it.)
- **Standalone binary** (`install.sh`): `bun build --compile` →
  `~/.local/bin/readback-cli`. The repo root is baked in via
  `--define process.env.READBACK_ROOT` because `import.meta.dir` is virtual
  inside a compiled binary (`server.ts` falls back to it in dev).
  `react-devtools-core` is a bundled devDependency — ink imports it behind a
  runtime `DEV` check the bundler can't eliminate. The binary is named
  `readback-cli` (not `readback`) so the server-lookup fallback
  `Bun.which("readback")` can't spawn the CLI itself.
- **Prefs** (voice/mode/model) persist to `~/.readback/cli.json`. Theme = the
  Ghost palette (#f0f0f0 primary, #808080 dim, #ff5d5d errors/cancel —
  inherited from the deleted web UI)
  plus CLI-only fit colors (#5dd17a green / #e6c35a yellow, `/model` list only)
  and an Xcode-blue accent (#4da3ff: wordmark "BACK", version, caret,
  progress fills, transcript highlight). Banner = half-block wordmark in
  `Header.tsx`; tagline + hints render on the input screen only.

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
  untagged reasoning; the default `gemma4:26b` (and the lighter
  `nemotron-3-nano:4b` fallback) are clean.

## Remaining cleanup candidates (tracked in README.md → Roadmap)

- Generated WAVs in `~/.readback/reader/` grow unbounded (no rotation yet).

The v0.8.0 cleanup removed the dead `tools/` module, the streaming/tool-calling
LLM plumbing, the legacy vanilla-JS static bundle, the inert `CsmTTSConfig`
fields (`speed`/`model`/`watermark`/`context_turns`), `OllamaConfig.system_prompt`,
and the Qwen→CSM config migration.

## Install & verification

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .                          # csm-mlx is a git dep (allow-direct-references)
readback                                  # starts the server (or: python -m readback)
cd src/cli && bun install && bun run start    # terminal CLI from source (auto-spawns the server)
cd src/cli && ./install.sh                    # or: standalone binary → ~/.local/bin/readback-cli
```

Smoke test: paste an article URL → Full mode → player appears, audio plays,
download works. Summary mode → transcript toggle shows the spoken summary. CLI:
`bun run start` with no server running → it spawns one, a pasted URL reads and
plays via afplay, q exits and the spawned server dies. Voice
work: `Synthesizer(Config.load().tts).synthesize("…")` from a Python REPL.

## Version

Current: **v2.0.0** — CLI-only pivot: web frontend removed, package restructured
(`reader/` → `pipeline/`, `web/` → `server/`), `cryptography` dep dropped,
TLS flags removed, then the folder restructure: `src/` layout (`src/readback`,
`src/cli`, `src/voice`, `src/finetune`) + docs collected under `docs/`
(ARCHITECTURE / SETUP / PLAN / media). Breaking change: browser UI gone,
`--auto-cert`/`--cert`/`--key` removed, `readback.reader.*` / `readback.web.*`
imports gone.
(v1.1.0: CLI model switch `/model` with RAM-fit verdicts. v1.0.0: terminal CLI
as a `/ws` client. v0.8.0: offline article reader pivot; CSM-1B via csm-mlx;
renamed `local-tts` → `readback`.) Set in `pyproject.toml`,
`src/readback/__init__.py`, and `src/cli/package.json`. Bump all three when
releasing.
