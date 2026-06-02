# local-tts — Project Context

A local voice + text assistant with a browser UI. Speak or type → STT → Ollama
LLM (with optional tools) → TTS → playback, all on-device. Speech-to-text is a
**dual engine** (NVIDIA Parakeet via MLX, default + streaming; faster-whisper as
a batch alternative), with **Smart-Turn v3** semantic end-of-turn on top of
webrtcvad. TTS is **Qwen3-TTS** (mlx-audio). Optional second-brain layer
auto-files every conversation as a markdown transcript in an Obsidian vault.

This project is **web-only**. The CLI is one command (`local-tts`) that boots
a FastAPI server and serves a React UI; there is no terminal conversation mode,
no PTT, no `click`/`rich`. If you see references to `cli.py`, `app.py`,
`audio/recorder.py`, `ui/display.py`, or `pynput` in older docs/PRs, that
codebase is gone.

**See [ARCHITECTURE.md](ARCHITECTURE.md)** for the system-level view — the
streaming cascade, the concurrency/threading model (event loop + ASR worker +
per-engine MLX executors + LLM producer thread), the turn lifecycle, and
extension points. This file holds the implementation notes, gotchas, and exact
knobs; ARCHITECTURE.md holds the "how it fits together / why."

## Hardware

- Apple M5 Pro, 48 GB unified memory (primary target).
- No CUDA. Accelerator mapping: **MLX/Metal (20-core GPU)** runs Parakeet ASR and
  Qwen3-TTS; **CPU** runs Whisper (CTranslate2 ARM NEON int8) and Smart-Turn
  (onnxruntime); Ollama runs Nemotron. **MLX is not multi-thread safe** — its
  default GPU stream binds to the thread that first touches the device, so
  Parakeet and Qwen each own a single-thread executor (see STT/TTS sections).

## Stack

- **LLM**: Ollama, default **`nemotron-3-nano:4b`** (NVIDIA) with `think=False`
  + `<think>` stripping. Any pulled model is selectable (`nemotron3:33b`,
  `qwen3`, …); tool-capable models required when `tools.enabled: true`.
- **TTS**: **Qwen3-TTS-0.6B** (`mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit`)
  via `mlx-audio` on Metal, 24 kHz, 9 preset speakers. (Kokoro was removed; the
  `Synthesizer` facade keeps a one-engine seam for re-adding it.)
- **STT**: **dual engine** behind an `ASREngine` protocol — Parakeet (MLX,
  default, streaming) + Whisper (faster-whisper, batch); switchable at runtime.
- **Turn detection**: Smart-Turn v3 (pipecat `smart-turn-v3.2-cpu.onnx`) via
  onnxruntime, hybrid with webrtcvad; graceful VAD-only fallback.
- **Wake-word**: openWakeWord backend exists (`local_tts/wakeword/`, optional
  `[wakeword]` extra) but the UI surface is currently hidden — see Wake-word
  section for why and how to re-enable.
- **Server**: FastAPI + WebSocket, single endpoint `/ws` per session.
- **Frontend**: React 18 + TypeScript + Vite + zustand. three.js point-cloud
  orb. Built into `local_tts/web/static/dist/`; the server serves the dist
  build when present, falls back to the legacy `static/index.html` bundle when
  the user hasn't run `npm run build` yet (rare; only useful for first-time
  setup before they install Node).

## Project Structure

```
local-tts/
├── pyproject.toml             # v0.5.0; parakeet-mlx + mlx-audio + onnxruntime + transformers<5
├── config.yaml                # user-editable; stt:/turn:/tts: blocks, Nemotron default
├── README.md                  # user-facing; mirror for changelog
├── ARCHITECTURE.md            # system-level view: cascade, threading model, lifecycle
├── voice/                     # reference clips for Qwen3-TTS voice cloning
│                              # (e.g. intro.wav); *.wav is gitignored — local only
├── scripts/
│   └── make_clone_voice.sh    # ffmpeg re-encode ANY audio → mono/24k/16-bit PCM
│                              # wav; default out-dir = ./voice; prints config snippet
│
└── local_tts/
    ├── __main__.py            # `local-tts` entry: argparse, optional --auto-cert/--cert/--key,
    │                          # uvicorn boot, banner with TLS fingerprint
    ├── config.py              # Pydantic config; STTConfig/TTSConfig/TurnConfig; load() drops
    │                          # unknown top-level keys, migrates legacy whisper:/ollama.system_prompt,
    │                          # resolves relative clone wav paths against the config file's dir
    │
    ├── llm/client.py          # LLMClient: Ollama streaming (think=False), _ThinkStripper,
    │                          # sentence splitter, persona snapshot, tool-call probe loop
    ├── stt/                   # dual ASR engine
    │   ├── base.py            # ASREngine Protocol + shared resample()
    │   ├── whisper_engine.py  # WhisperEngine (faster-whisper, batch); SUPPORTED_MODELS
    │   ├── parakeet_engine.py # ParakeetEngine (parakeet-mlx, streaming); single-thread MLX
    │   │                      # executor; transcribe_stream/add_audio; SUPPORTED_MODELS
    │   ├── transcriber.py     # Transcriber facade: swap_engine/swap_model/streaming_engine
    │   └── turn.py            # TurnDetector: Smart-Turn v3 ONNX; probability()/is_complete()
    ├── tts/                   # Qwen3-TTS (Kokoro removed)
    │   ├── qwen_engine.py     # QwenEngine (mlx-audio); single-thread MLX executor;
    │   │                      # generate_custom_voice; SUPPORTED_VOICES (9 speakers)
    │   └── synthesizer.py     # Synthesizer facade over QwenEngine (same server surface)
    │
    ├── tools/                 # function-calling
    │   ├── base.py            # Tool protocol (name, schema, run(args) -> str)
    │   ├── registry.py        # ToolRegistry: allowlist filter + dispatch
    │   ├── clock.py           # local time
    │   └── web_search.py      # DDG HTML scraper; WebSearchProvider Protocol for swap-in providers
    │
    ├── memory/                # session persistence + topic-organized markdown export
    │   ├── session_writer.py  # SessionWriter: JSONL mirror + finalize() writes markdown
    │   └── topic_classifier.py  # LLM call → folder slug (sanitized regex)
    │
    ├── wakeword/
    │   └── detector.py        # lazy openWakeWord wrapper; auto-downloads models and
    │                          # forces inference_framework="onnx" (no tflite-runtime on Apple Silicon)
    │
    └── web/
        ├── server.py          # FastAPI app, Session class, WS protocol, VAD utterance
        │                      # segmentation, tools/persona/wakeword/voice swap handlers
        ├── static/            # legacy vanilla-JS fallback + Vite output:
        │   ├── index.html     # legacy bundle (still served if dist/ is missing)
        │   ├── app.js         # legacy bundle (1295 lines; superseded by React)
        │   ├── styles.css     # legacy bundle
        │   ├── recorder.worklet.js   # AudioWorklet: mic → 16k Int16 PCM (used by BOTH bundles)
        │   └── dist/          # Vite build output — `npm run build` writes here
        └── frontend/          # React app source — vite build target = ../static/dist
            ├── package.json   # react, react-dom, three, zustand
            ├── vite.config.ts # outDir: '../static/dist'
            └── src/
                ├── main.tsx, App.tsx
                ├── components/    # Header (6 chips), Dock, Captions, SettingsModal,
                │                  # TypePopover, MicMeter, OrbContainer, Picker, icons
                ├── lib/           # ws.ts, audioEngine.ts, brain.ts (three.js), prefs.ts
                └── state/         # zustand store
```

## Critical Implementation Notes

### Server pipeline (web/server.py)

- Single `Session` per WebSocket connection. STT(batch)/LLM/TTS run inside
  `asyncio.to_thread` so the event loop stays free for the audio fan-in.
- **Streaming ASR worker** (`_asr_worker_loop`, Parakeet only): a dedicated
  thread consumes mic frames from a `queue.Queue`, feeds the live stream, emits
  `{"type":"partial"}` via `loop.call_soon_threadsafe`, and on end-of-turn
  finalizes → launches the pipeline with the streamed text (batch fallback if
  empty). `_awaiting_finalize` gates late frames during the launch window.
  Whisper has no streaming API and uses the batch path (`_dispatch_utterance`).
- LLM streaming runs in a producer **thread** that pushes finished sentences
  onto an `asyncio.Queue` via `loop.call_soon_threadsafe`. The consumer races
  each `queue.get()` against `interrupt_event` so Skip takes effect mid-sentence.
  For each sentence, TTS is synthesized in full (`synth.synthesize`, batch) and
  sent as one buffer — per-chunk model streaming was tried and reverted (it chops
  on the slow clone Base model; see TTS section).
- Mic frames are dropped while `pipeline_task is not None`, during
  `_awaiting_finalize`, AND while `_speaking` (the speaker-bleed guard). The
  bytes-sent ≠ bytes-played gap matters: the server finishes sending TTS long
  before the browser finishes *playing* the queued buffers, so `_speaking` stays
  set until the client posts `playback_done` (then a `SPEAKING_COOLDOWN_SEC`
  reverb cooldown), with a duration-based fallback (`_arm_playback_guard`:
  audio-seconds-sent + cooldown + slack) so a lost message can't wedge the mic
  shut. `_begin_speaking()` at phase=speaking; `_stop_speaking()` on
  interrupt/mute (nothing audible → reopen immediately). If a future change
  accepts audio during speaking, **this gate must be replaced** or the wake-word
  detector self-fires.
- Utterance segmentation: 8 speech frames to start (~240 ms), 25 silence frames
  (~750 ms) → **candidate** end-of-turn confirmed by Smart-Turn (re-checked every
  ~300 ms, forced at `turn.max_wait_sec`), 12-frame minimum (~360 ms).

### Wake-word (deferred — UI hidden, backend retained)

**Why hidden:** openWakeWord's bundled keywords are `alexa`, `hey_jarvis`,
`hey_mycroft`, `hey_rhasspy`, `timer`, `weather`. Custom keywords require
multi-hour training via openWakeWord's notebook. Free-tier custom-keyword
support is planned via a Picovoice Porcupine backend; until then the picker
in `SettingsModal.tsx` and the `mode` chip in `Header.tsx` are commented out
and `config.yaml` ships the `wakeword:` / `input:` blocks commented out.

**What still works:** the backend stack — `detector.py`, server WS handler
(`set_input_mode`), `_handle_input_mode`, the `_process_frame` wake-word gate
— is unchanged. To re-enable:
1. Uncomment the `wakeword:` and `input:` blocks in `config.yaml`.
2. Restore the listening-mode picker in `SettingsModal.tsx` (the prop is
   `onChangeInputMode`; the WS message is `set_input_mode`).
3. Restore the `mode` chip in `Header.tsx`.
4. `pip install -e ".[wakeword]"` if not already.

**Implementation notes (still accurate):**
- Loaded lazily. `WakeWordUnavailable` raised on import or model-load
  failure; server reports back as an `input_mode` error WS message without
  changing the actual mode.
- **Always uses ONNX on Apple Silicon.** `tflite-runtime` has no Apple
  Silicon wheel. `detector.py` derives the framework: built-in keyword OR
  `.onnx` path → onnx; only an explicit `.tflite` custom path uses tflite.
- **Auto-downloads models** on first load via
  `openwakeword.utils.download_models([name])` — the wheel ships no model
  files. ~7 MB total: feature models (`melspectrogram`, `embedding`,
  `silero_vad`) + the chosen wake word in both .tflite + .onnx variants.
- Frame contract: `process_int16(frame: bytes)` accepts arbitrary-length
  int16 mono PCM at 16 kHz. Internal buffer flushes 1280-sample (80 ms)
  blocks to the detector.
- `_reset_vad()` clears `wake_triggered` AND calls `detector.reset()` on
  every utterance boundary, so each new utterance requires a fresh trigger.

### Tools (llm/client.py + tools/)

- `tools.enabled: true` switches `stream_response()` into the
  `_stream_tokens_with_tools` branch: non-streaming probe → if `tool_calls`,
  run + append result as `{role: "tool", name, content}` → re-probe. Capped
  at `_MAX_TOOL_HOPS = 3`. After the cap (or when no tool_calls are returned),
  a final streaming chat call yields tokens to the sentence splitter.
- We deliberately don't stream during tool-call hops — partial planning
  preamble speaks awkwardly before the actual answer.
- `ToolRegistry.run()` never raises; tool failures become string content the
  model can read and recover from (`[tool error] <name>: <msg>`).
- `web_search` uses a `WebSearchProvider` Protocol (`name`, `search(query, k)`).
  Only `DuckDuckGoProvider` ships today; `build_default_provider(name)` is
  the only place to add Tavily/Brave. Provider parses HTML with the stdlib
  `html.parser`, no extra deps.

### Persona (llm/client.py)

- `PersonaConfig` seeds three personas (`default`, `concise`, `researcher`)
  via `_default_personas()`. A 4th `custom` slot is created on first
  `set_custom_prompt()` call from the UI.
- `swap_persona(name)` mirrors `Transcriber.swap_model`: `threading.Lock`,
  atomic write of `personas.active`. `stream_tokens()` snapshots
  `active_persona.system_prompt` once at the top so an in-flight response
  finishes on its original prompt — no half-swap mid-sentence.
- Legacy `ollama.system_prompt` in `config.yaml` is migrated at load time:
  if the user has it set AND no `persona` section, the value overrides the
  seeded `default` persona's prompt. Other seed personas stay intact.

### Obsidian / session persistence (memory/)

- `SessionWriter` is constructed per session unconditionally; all methods are
  no-ops when `obsidian.enabled: false`, so wiring stays the same regardless
  of feature state.
- `start()` opens `<memory.session_dir>/<sid>.jsonl` (tilde-expanded) and
  appends `{event: "start", ...}`. Each `append_turn()` appends a
  `{event: "turn", role, text, ts}` line — crash-recovery mirror.
- `finalize(llm)` runs at WS disconnect on a background thread
  (`asyncio.to_thread`, fire-and-forget). On sessions with ≥2 turns it calls
  `propose_topic(llm, summary)`; <2 turns lands in `unsorted/`.
- Topic classifier uses `temperature=0` and `_sanitize()` regex-clamps the
  reply to `[a-z0-9-]{1,32}`. Anything outside falls back to `UNSORTED` so
  a hallucinated path-traversal answer can't escape the vault root.
- Final markdown is `<vault_root>/<topic>/YYYY-MM-DD--<sid_prefix>.md` with
  YAML frontmatter (`session_id`, `started`, `ended`, `duration_sec`, `model`,
  `voice`, `persona`, `topic`, `turn_count`) + human-readable turn-by-turn body.
- JSONL is deleted on successful markdown commit.

### TTS — Qwen3-TTS (tts/qwen_engine.py, tts/synthesizer.py)

- `QwenEngine` wraps `mlx_audio.tts.utils.load_model(...)` +
  `generate_custom_voice(text, speaker, instruct)`. Output is float32 @ **24 kHz**
  (native — matches the WS contract, no resample).
- **Batch per sentence (server default).** `_run_pipeline` calls `synthesize()`
  per sentence and sends the whole sentence as one buffer. Playback is gapless
  *within* a sentence regardless of synth speed; the only stall is *between*
  sentences, absorbed by the client jitter buffer (`audioEngine.ts`
  `LEAD_SEC=0.28`).
- ⚠ **Per-chunk model streaming exists but the server does NOT use it.**
  `synthesize_stream(text, should_stop)` yields a sentence's audio in chunks as
  the model produces them (`stream=True, streaming_interval=STREAM_INTERVAL_SEC=0.5`;
  generator on the MLX executor thread, chunks bridged out via a bounded
  `queue.Queue`; `should_stop` `gen.close()`s on interrupt). It cuts first-audio
  latency on **fast** engines (preset CustomVoice, RTF ~0.21 → first audio
  ~0.12 s, chunk boundaries measured continuous). But on a **slow** engine — the
  cloned **Base** model (RTF near realtime) — each 0.5 s chunk must *arrive* in
  realtime; when it can't, the client queue underruns *mid-sentence* and chops.
  So streaming was tried (Phase 7) and reverted to batch. Kept as opt-in API for
  a future "stream only when the engine is fast enough" path.
  `_build_gen(text, stream)` is shared by both `synthesize` and `synthesize_stream`.
- **MLX single-thread:** like Parakeet, MLX binds its GPU stream to the first
  thread that touches the device. `QwenEngine` owns a `ThreadPoolExecutor(max_workers=1)`
  and runs ALL model work (load + synth) on it; public methods submit and block.
  `_impl` methods run on that thread and must never re-submit.
- First load downloads the model and **warms the graph** (cold first synth ~2.4 s;
  warm RTF ~0.21 on M5, ~664 ms for a 3.2 s clip).
- `SUPPORTED_VOICES` = 9 `(speaker_id, label)` pairs; `swap_voice()` just sets
  `cfg.speaker` (a per-call arg — instant, no reload).
- `Synthesizer(TTSConfig)` is a thin facade keeping the server surface
  (`synthesize`, `sample_rate`, `current_voice`, `swap_voice`, `load`). Kokoro
  was removed; `cfg.tts.engine` is a single-value enum for a future re-add.
- ⚠ `generate_custom_voice` has no `speed` arg (only `generate()` does) → the UI
  speed slider is currently a no-op for Qwen.

#### Reference-audio voice cloning (`tts.qwen.clones`)

- Beyond the 9 presets, `config.yaml` can list cloned voices under
  `tts.qwen.clones` (`CloneVoiceConfig`). Each appears in the UI picker as
  `clone:<name>`. Cloning uses the **Base** checkpoint (`qwen.base_model`), not
  CustomVoice — selecting a clone reloads Base (~1.2 GB first use); picking a
  preset reloads CustomVoice. One model is loaded at a time.
- A clone entry: `name`, `wav` (reference clip), optional `label`, `ref_text`
  (transcript in the clip's OWN language — auto-filled via Whisper if omitted),
  `ref_lang`, `instruct` (emotion/style — shapes HOW it speaks; the wav sets
  WHO), and per-clone `speed`/`temperature`. `QwenEngine._ref_for` returns
  `(expanded wav path, cached ref_text)`; the server resolves/caches `ref_text`
  off the MLX thread before synth.
- **Reference clips live in the project `voice/` folder.** `wav:` is resolved in
  `Config.load()`: a **relative** path (e.g. `voice/intro.wav`) is anchored to
  the **config file's directory** (not the launch CWD); absolute and `~/…` paths
  are left as written. So clones are portable regardless of where `local-tts`
  is started. `*.wav` is gitignored — clips stay local.
- **`scripts/make_clone_voice.sh`** prepares clips: re-encodes ANY audio/video
  (m4a/mp3/mp4/…) to the mono/24 kHz/16-bit PCM wav the Base model can load
  (a renamed `.m4a` will NOT decode), optional `-s/-d` trim, `--batch` a folder.
  Default out-dir is the project `./voice`; it prints a ready-to-paste
  `tts.qwen.clones` snippet.

### STT — dual engine (stt/)

- `ASREngine` protocol (`stt/base.py`): `supported_models`, `current_model`,
  `load`, `swap_model`, `transcribe(audio, sr)`, `supports_streaming`. Shared
  `resample()` enforces the 16 kHz contract. `Transcriber` (transcriber.py) is a
  facade over both engines: `current_engine`, `engines_available`,
  `models_for(engine)`, `swap_engine`, `swap_model`, `streaming_engine()`.
- **ParakeetEngine** (default, `parakeet_engine.py`): MLX/Metal. `transcribe()`
  is file/ffmpeg-only upstream, so we route BOTH batch and streaming through
  `transcribe_stream` + `add_audio(mx.array)`. Owns a **single-thread executor**
  (same MLX rule as Qwen). `add_audio` underflows on <~100 ms chunks, so the
  engine buffers mic frames to `stream_chunk_ms` (320 ms) per encoder step.
  Streaming: `start_stream/feed/finalize/abort_stream`. ~2.5 GB first download.
- **WhisperEngine** (`whisper_engine.py`, batch): the old faster-whisper code
  verbatim — CPU int8, `threading.Lock` swap, all hallucination guards
  (`no_speech_threshold=0.6`, `log_prob_threshold=-1.0`, `vad_filter`, …) and the
  `mel_filters @ magnitudes` RuntimeWarning filter. Sizes tiny→large-v3.

### Turn detection — Smart-Turn v3 (stt/turn.py)

- `TurnDetector` runs `pipecat-ai/smart-turn-v3.2-cpu.onnx` (Whisper-tiny encoder
  + linear head) via onnxruntime. `WhisperFeatureExtractor(chunk_length=8)` →
  `input_features (1,80,800)` over the last 8 s → sigmoid `P(turn complete)`;
  ≥`threshold` (0.5) ends. ~7–12 ms/call.
- Loaded once in `PipelineModels.load` with graceful fallback: on
  `TurnDetectorUnavailable` (offline / deps) `turn_detector=None` → VAD-only.
- Server gate `_turn_is_complete()` runs it off-loop (`to_thread`) at the
  webrtcvad pause; if incomplete keeps listening and emits `{"type":"turn"}`.

### Sentence streaming + reasoning (llm/client.py)

- Default model `nemotron-3-nano:4b`; all three `chat()` calls pass `think=False`.
  `_ThinkStripper` removes `<think>…</think>` from the streamed token feed even
  across chunk boundaries (drops unclosed think on flush); `strip_think()` is the
  one-shot for the non-streaming tool probe. NOTE: `qwen3` ignores `think=False`
  and emits untagged reasoning — model-specific, not strippable.
- Split on `.`, `!`, `?` followed by whitespace; min 8 chars per sentence.
- Sub-min fragments are stitched onto the next part rather than yielded —
  prevents "Mr." or "3.14" from speaking solo.
- `_strip_markdown` regex: `^[>#\-\*]+\s*` (NOT `^[\s>#\-\*]+`). The latter
  ate leading whitespace from per-token chunks like `" am"` → `"am"`,
  collapsing streamed output into `"Iamsorry"`. Keep `\s` out of the class.
- History trimmed to `ui.history_turns * 2` messages before each Ollama call
  (user + assistant = 1 turn).

## WebSocket protocol (`/ws`)

Client → server:
- Binary: raw Int16 PCM @ 16 kHz mono (mic audio).
- JSON: `mute`, `unmute`, `interrupt`, `text_input {text}`, `set_voice {voice}`,
  `set_stt_engine {engine: "parakeet"|"whisper"}`, `set_stt_model {model}`,
  `set_model {model}` (Ollama LLM swap), `set_speed {speed}`,
  `set_persona {name}`, `set_persona_custom_prompt {prompt}`,
  `set_input_mode {mode: "vad"|"wake_word"}`, `set_tools_enabled {value: bool}`,
  `set_tool_allowed {tool, value: bool}`, `playback_done` (client finished
  playing the queued TTS → server reopens the mic after a reverb cooldown).

Server → client:
- Binary: raw Float32 PCM @ 24 kHz mono (TTS output).
- JSON: `phase {value}`, `transcript {role, text, session_id}`,
  `partial {text, session_id}` (live streaming ASR, Parakeet),
  `turn {state: "waiting", prob}` (Smart-Turn mid-thought pause), `level {value}`,
  `config {session_id, voice, voices_available, model, models_available,
  stt_engine, stt_engines_available, stt_model, stt_models_available,
  turn_enabled, speed, persona, personas_available, tools_enabled,
  tools_available, tools_allowed, input_mode, wakeword_model, obsidian_enabled}`,
  `error {message}`, `stt_model {state: loading|ready|error, model, message?}`,
  `stt_engine {state, engine, model?, models_available?, message?}`,
  `voice {state, voice, message?}`, `model {state, model}`,
  `persona {state, name, personas_available?, message?}`,
  `input_mode {value, state?, message?}`,
  `tools_enabled {value}`, `tools_allowed {value}`.

### Reconnect behavior (App.tsx config-message handler)

The `config` payload arrives on every connect and re-seeds the store. The
client then **only** re-emits saved prefs for `sttEngine`, `sttModel`, `voice`,
and `speed` that diverge from server defaults (`sttEngine` first, so the model
list reflects the right engine). Persona / tools-enabled / inputMode /
customPrompt are received from the server but **not** sent back on reconnect —
those mirror `config.yaml` on each fresh connection.

## Frontend (web/frontend/)

- React 18 functional components, single `App.tsx` orchestrator. The audio
  engine, WS client, and three.js brain controller live OUTSIDE the React
  tree as singletons; they push events into a zustand store, so React
  re-renders never tear down the socket or audio context.
- Header is five clickable chips (`voice` · `model` · `persona` · `tools` ·
  `vault`). Every chip opens Settings. The ASR control is **two-level** in
  Settings: an engine selector (Parakeet ★ / Whisper, hidden when only one
  engine) above the model picker, which the server filters to the active engine.
  Live partials render dimmed in the INPUT caption; a "Listening — go on…" hint
  shows while `turnWaiting`.
- INPUT label animates per phase: `LISTENING_` (blinking cursor CSS) /
  `PROCESSING ···` (dots reveal) / `Input` (fallback). The animations are
  pure CSS classes flipped from `setPhase()`.
- `AudioWorkletProcessor` (`recorder.worklet.js`) downsamples device-native
  rate (typically 48 kHz) → 16 kHz Int16 in ~60 ms chunks. Output uses
  `AudioBufferSourceNode` queued at `state.playbackTime` for gapless playback.
  An `AnalyserNode` drives the orb scale via `requestAnimationFrame` while
  `phase === "speaking"`.
- **Single theme: Ghost** — `--accent: #f0f0f0`, matte white/grey. Theme
  picker reserved (commented out in HTML); store keeps `theme: "ghost"`.
- Prefs key: `localStorage["local-tts.prefs.v10"]`. `loadPrefs()` chains legacy
  migrations (v9/v8); v10 adds `sttEngine`. Bump the key on any schema change.

## CLI

```
local-tts                                  # http://127.0.0.1:8000
local-tts --host 0.0.0.0 --port 8000       # LAN reachable (HTTP)
local-tts --host 0.0.0.0 --auto-cert       # LAN + auto self-signed cert; banner
                                           # prints SHA-256 fingerprint + /cert.pem URL
local-tts --host 0.0.0.0 --cert c.pem --key k.pem   # bring your own cert
local-tts --model nemotron3:33b            # override ollama.model for this run
local-tts --config /path/to/config.yaml    # custom config
```

Auto-cert: stored at `~/.local-tts/certs/{cert,key}.pem`, regenerated when
the detected LAN IP changes (tracked in `cert.meta.json`). Cert SAN includes
the LAN IP, `127.0.0.1`, and `localhost`. 825-day validity matches Safari's
trust ceiling.

## Voice options (Qwen3-TTS)

`SUPPORTED_VOICES` (tts/qwen_engine.py) = 9 preset speakers, exposed via
`config.voices_available`:
- Male: `ryan` ★, `eric`, `aiden`, `dylan`, `uncle_fu`
- Female: `serena` ★, `vivian`, `ono_anna`, `sohee`

`swap_voice()` just sets `cfg.tts.qwen.speaker` (per-call arg — instant). The
optional `qwen.instruct` field is a voice-design hint (e.g. "warm, fast").

Plus any **cloned voices** from `tts.qwen.clones` (id `clone:<name>`) — reference
clips in the project `voice/` folder, prepped via `scripts/make_clone_voice.sh`.
See the cloning subsection under "TTS — Qwen3-TTS" for the full picture.

## Latency budget (M5 — measured in P1/P4b)

| Stage | Value |
|---|---|
| VAD silence-end gate | ~750 ms |
| Smart-Turn v3 decision | ~7–12 ms (CPU) |
| Parakeet streaming finalize | near-zero (most already streamed) |
| Parakeet batch (4.7s clip) | ~1.1 s cold / RTF ~0.24 |
| Whisper medium batch (4.7s clip) | ~2.9 s / RTF ~0.61 |
| Nemotron-3-nano:4b first sentence | ~1.3 s cold (~200–500 ms warm) |
| Qwen3-TTS first sentence | warm RTF ~0.21 (batch per sentence; streaming reverted, P7) |

Tool-call probes add one full Ollama non-streaming round-trip per hop
(usually 400–800 ms) before the final response streams. Three hops max.

## Echo / feedback handling

The web browser's `getUserMedia({ echoCancellation: true })` handles AEC, so
there's no PTT key, no RMS gate, no headphones requirement. AEC alone is not
enough on built-in MacBook speaker+mic (loud, non-linear echo close together),
so the **`_speaking` mic gate** (see Server pipeline) keeps the mic closed for
the full *playback* duration — not just until the bytes are sent — plus a short
reverb cooldown, which is what stops the assistant hearing its own reply.
Whisper's hallucination guards (see STT section) handle the residual "AI bleed
during LISTENING" case on near-silent buffers.

## Install & verification

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch==2.4.0 torchaudio==2.4.0   # pinned; transformers<5 needs this torch
pip install -e .
pip install -e ".[wakeword]"             # optional; only if you re-enable the wake-word UI
cd local_tts/web/frontend && npm install && npm run build && cd ../../..
local-tts                                # boots; opens http://127.0.0.1:8000
```

**Dependency note:** `transformers` is pinned `<5`. mlx-audio declares
`transformers>=5.5`, but 5.x's import chain needs torch≥2.5
(`torch.distributed.tensor.device_mesh`); Qwen3-TTS and Smart-Turn both run fine
on transformers 4.x with torch 2.4, so we override the pin.

First launch (weights download silently on first use):
1. Parakeet (~2.5 GB), Qwen3-TTS-0.6B, Smart-Turn v3 (~8 MB). `nemotron-3-nano:4b`
   must be pulled in Ollama (`ollama pull nemotron-3-nano:4b`).
2. Open the page → orb breathes, "STANDBY" status.
3. Say "hello" → live partial caption appears → reply streams + speaks.
4. Settings → switch ASR engine Parakeet↔Whisper; switch speaker.
5. (Tools on) Say "what time is it" → log shows `tool_call: clock -> N chars`.
6. (Obsidian on) 2+ turn convo, close tab → markdown lands in the vault.

## Things that look like bugs but aren't

- **Wake-word first-load delay (~2–5 s, no UI feedback).** If the UI is
  re-enabled, `download_models` blocks the WS handler thread (it's wrapped
  in `asyncio.to_thread`, so the event loop is free, but the UI shows no
  spinner). Track via a new `wakeword {state: downloading|loading|ready|error}`
  WS message when the picker is revived.
- **Tools cause first-token delay even on tool-free answers.** The probe is
  always non-streaming because we can't know up-front whether the model will
  ask for a tool. Toggling tools OFF in Settings restores streaming first-token.
- **Markdown export silently noops if `obsidian.enabled: false`.**
  `SessionWriter` is constructed unconditionally but all methods early-return.
  Toggle the config flag, restart the server.
- **Persona "custom" doesn't appear in personas_available until first save.**
  It's added to `PersonaConfig.personas` on first `set_custom_prompt` call.
  Cosmetic only.
- **First Qwen3-TTS / Parakeet utterance is slow (~2–3 s).** One-time MLX graph
  warm-up; `load()` pre-warms but the very first real synth/transcribe still pays
  some compile cost. Warm calls are near-real-time.
- **`<think>` leaks only on qwen3, not Nemotron.** `qwen3` ignores `think=False`
  and emits untagged reasoning prose — no stripper can catch untagged text. The
  default `nemotron-3-nano:4b` is clean. Pick a different model if it bothers you.
- **Speed slider does nothing on Qwen3-TTS.** `generate_custom_voice` has no
  `speed` arg (only `generate()` does). Left as a no-op until ref-voice mode.
- **MLX "no Stream(gpu, 0)" if you call Parakeet/Qwen off their executor.** Both
  engines MUST run all model work on their own single-thread executor; never call
  the `_impl` methods or `mx` ops from another thread.

## Roadmap candidates (not committed)

- Round-trip persona/tools/inputMode/customPrompt prefs on reconnect (currently
  only sttModel/voice/speed are re-emitted in `App.tsx:78-100`).
- Wake-word download progress over WS.
- More search providers behind `WebSearchProvider` (Tavily, Brave).
- Long-term `memory.md` separate from session JSONL — explicit `remember(...)`
  tool, never auto-extracted.
- Wake-lock + PWA manifest for phone hands-free use.

## Version

Current: **v0.5.0** (Open-model voice pipeline: dual ASR + Smart-Turn + Nemotron
+ Qwen3-TTS). Set in `pyproject.toml` and `local_tts/__init__.py`. Bump both when
releasing. See [README.md#changelog](README.md#changelog) for release notes.
