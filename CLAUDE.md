# readback — Project Context

A local voice + text assistant with a browser UI. Speak or type → STT → Ollama
LLM (with optional tools) → TTS → playback, all on-device. Speech-to-text is
**NVIDIA Parakeet** via MLX (streaming, the sole ASR engine — faster-whisper was
dropped in v0.7.0), with **Smart-Turn v3** semantic end-of-turn on top of
webrtcvad. TTS is **CSM-1B** (Sesame, via mlx-audio). Optional second-brain layer
auto-files every conversation as a markdown transcript in an Obsidian vault.

This project is **web-only**. The CLI is one command (`readback`) that boots
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
  CSM-1B TTS; **CPU** runs Whisper (CTranslate2 ARM NEON int8) and Smart-Turn
  (onnxruntime); Ollama runs Nemotron. **MLX is not multi-thread safe** — its
  default GPU stream binds to the thread that first touches the device, so
  Parakeet and CSM each own a single-thread executor (see STT/TTS sections).

## Stack

- **LLM**: Ollama, default **`nemotron-3-nano:4b`** (NVIDIA) with `think=False`
  + `<think>` stripping. Any pulled model is selectable (`nemotron3:33b`,
  `qwen3`, …); tool-capable models required when `tools.enabled: true`.
- **TTS**: **CSM-1B** (`mlx-community/csm-1b`, Sesame Conversational Speech Model;
  the open base MisoTTS is built on) via `mlx-audio` on Metal, 24 kHz, 2 preset
  voices + reference-audio clones. English-best. (Qwen3-TTS was replaced in
  v0.6.0; the `Synthesizer` facade keeps a one-engine seam for a future
  MisoTTS-8B port.)
- **STT**: **Parakeet** (MLX, streaming) behind an `ASREngine` protocol — the
  sole ASR engine (faster-whisper dropped in v0.7.0; the protocol/facade seam is
  kept so a second engine stays a one-file addition).
- **Turn detection**: Smart-Turn v3 (pipecat `smart-turn-v3.2-cpu.onnx`) via
  onnxruntime, hybrid with webrtcvad; graceful VAD-only fallback.
- **Wake-word**: openWakeWord backend exists (`readback/wakeword/`, optional
  `[wakeword]` extra) but the UI surface is currently hidden — see Wake-word
  section for why and how to re-enable.
- **Server**: FastAPI + WebSocket, single endpoint `/ws` per session.
- **Frontend**: React 18 + TypeScript + Vite + zustand. three.js point-cloud
  orb. Built into `readback/web/static/dist/`; the server serves the dist
  build when present, falls back to the legacy `static/index.html` bundle when
  the user hasn't run `npm run build` yet (rare; only useful for first-time
  setup before they install Node).

## Project Structure

```
readback/
├── pyproject.toml             # v0.6.0; parakeet-mlx + mlx-audio + onnxruntime + transformers<5
├── config.yaml                # user-editable; stt:/turn:/tts: blocks, Nemotron default
├── README.md                  # user-facing; mirror for changelog
├── ARCHITECTURE.md            # system-level view: cascade, threading model, lifecycle
├── voice/                     # reference clips for CSM-1B voice cloning
│                              # (e.g. intro.wav); *.wav is gitignored — local only
├── scripts/
│   └── make_clone_voice.sh    # ffmpeg re-encode ANY audio → mono/24k/16-bit PCM
│                              # wav; default out-dir = ./voice; prints config snippet
│
└── readback/
    ├── __main__.py            # `readback` entry: argparse, optional --auto-cert/--cert/--key,
    │                          # uvicorn boot, banner with TLS fingerprint
    ├── config.py              # Pydantic config; STTConfig/TTSConfig/TurnConfig; load() drops
    │                          # unknown top-level keys, migrates legacy qwen tts:/ollama.system_prompt,
    │                          # resolves relative clone wav paths against the config file's dir
    │
    ├── llm/client.py          # LLMClient: Ollama streaming (think=False), _ThinkStripper,
    │                          # sentence splitter, persona snapshot, tool-call probe loop
    ├── stt/                   # ASR (Parakeet only)
    │   ├── base.py            # ASREngine Protocol + shared resample()
    │   ├── parakeet_engine.py # ParakeetEngine (parakeet-mlx, streaming); single-thread MLX
    │   │                      # executor; transcribe_stream/add_audio; transcribe_file (clone refs)
    │   ├── transcriber.py     # Transcriber facade: swap_engine/swap_model/streaming_engine
    │   └── turn.py            # TurnDetector: Smart-Turn v3 ONNX; probability()/is_complete()
    ├── tts/                   # CSM-1B (Sesame; Qwen3-TTS replaced in v0.6.0)
    │   ├── csm_engine.py      # CsmEngine (mlx-audio "sesame" model); single-thread
    │   │                      # MLX executor; generate(voice=|ref_audio=); 2 presets + clones
    │   └── synthesizer.py     # Synthesizer facade over CsmEngine (same server surface)
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
  `_dispatch_utterance` (batch, non-streaming) remains as the fallback path for
  any engine that reports `supports_streaming = False`.
- **Phantom-utterance guard** (`_is_phantom_utterance`): Parakeet has no
  no-speech / log-prob hallucination guards (Whisper's did), so it transcribes
  TTS bleed, reverb, or background music into short backchannels. Any whole
  finalized ASR utterance that normalizes to a pure filler (`okay`, `mm-hmm`,
  `uh huh`, `thank you`, `hi`, …) is dropped before launching the pipeline,
  killing the self-reply loop. Applied to ASR text ONLY — typed input is never
  filtered; `yes`/`no` are kept. Pairs with the `_speaking` mic gate + the
  `SPEAKING_COOLDOWN_SEC` reverb cooldown.
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
- Utterance segmentation (config-tunable timings, ms → 30 ms frames per Session
  in `__init__`): voiced-ratio onset over a 10-frame pre-roll ring (internal),
  `vad.silence_end_ms` (480) of silence → **candidate** end-of-turn confirmed by
  Smart-Turn (re-checked every `turn.recheck_ms` (300), forced at
  `turn.max_wait_sec`), `vad.min_utterance_ms` (360) minimum. The post-playback
  echo cooldown is `vad.speaking_cooldown_ms` (600). Lower `silence_end_ms` for a
  fast talker — Smart-Turn backstops false early ends.

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

### System prompt (llm/client.py)

- The multi-persona system was removed in v0.7.x. `LLMClient` takes a single
  fixed `system_prompt` (`cfg.ollama.system_prompt`, defaulting to
  `DEFAULT_PERSONA_PROMPT` in config.py — sharp, tech-savvy + easygoing). Edit
  `ollama.system_prompt` in `config.yaml` to change the assistant's behavior.
  `stream_tokens()` prepends it as the system message; no runtime switching.

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

### TTS — CSM-1B (tts/csm_engine.py, tts/synthesizer.py)

CSM-1B (Sesame Conversational Speech Model) replaced Qwen3-TTS in v0.6.0. It's
the open base the MisoTTS family is built on; the MLX build
`mlx-community/csm-1b` (config `model_type: "sesame"`, ~6.2 GB F32) runs through
the **same mlx-audio** library, so this was a model swap, not a new dependency.

- `CsmEngine` wraps `mlx_audio.tts.utils.load_model("mlx-community/csm-1b")` +
  the `sesame.Model.generate(...)` **generator**. Output is float32 @ **24 kHz**
  (Mimi-native — matches the WS contract, no resample).
- **One model serves both paths, no checkpoint swap** (unlike Qwen's
  CustomVoice/Base split): presets via `generate(voice="conversational_a")`,
  clones via `generate(ref_audio=<wav>, ref_text=<transcript>)`. So preset↔clone
  swaps are **instant** — `swap_voice()` just sets `cfg.speaker`.
- **Batch per sentence (server default).** `_run_pipeline` calls `synthesize()`
  per sentence, sends the whole sentence as one buffer; gapless within a
  sentence, between-sentence stalls absorbed by the client jitter buffer
  (`audioEngine.ts` `LEAD_SEC=0.28`). Non-stream `generate()` yields exactly one
  `GenerationResult` per sentence.
- ⚠ **Per-chunk streaming exists but the server does NOT use it.**
  `synthesize_stream(text, should_stop)` drives `generate(stream=True,
  streaming_interval=0.5)`, bridging chunks off the MLX executor through a
  bounded `queue.Queue` (`should_stop` → `gen.close()`). Kept as opt-in API; the
  server stays on batch (same rationale as before — measure CSM RTF before
  enabling). `_build_gen(text, stream)` is shared by `synthesize` /
  `synthesize_stream`.
- **MLX single-thread:** like Parakeet, MLX binds its GPU stream to the first
  thread that touches the device. `CsmEngine` owns a
  `ThreadPoolExecutor(max_workers=1)` and runs ALL model work (load + synth) on
  it; public methods submit and block. `_impl` methods run on that thread and
  must never re-submit.
- First load downloads ~6.2 GB and **warms the graph** (`load()` runs one
  throwaway synth). `temperature`/`top_k` feed `make_sampler`; `max_audio_length_ms`
  is capped per-sentence (`_max_ms_for`) so a missing EOS can't hang the pipeline
  and the long preset voice-prompt stays under CSM's 2048-token budget.
- ⚠ **bf16 precision (NOT int8 quant) — `cfg.csm.precision`.** F32 CSM-1B runs
  RTF ~1.4 on M5 (stalls). We follow MisoTTS (same Sesame CSM architecture): run
  **bf16, no quantization**. `_load_impl` casts via `self._model.set_dtype(...)`.
  We previously int8 group-quantized (`nn.quantize`) for speed, but it
  **garbled/robotized the voice** — the Mimi-codec-skip predicate (a
  `_audio_tokenizer` path-prefix guess) couldn't be trusted across mlx-audio
  versions, and int8 carries per-op dequant overhead anyway. bf16 ~halves F32,
  has native Apple-Silicon matmul (no dequant), and keeps decode clean — at least
  as fast as int8 here. `precision`: `"bf16"` (default), `"fp16"` (a touch
  faster), `"fp32"` (cleanest, ~RTF 1.4, may stall). Memory isn't the constraint
  at 48 GB; clean realtime is.
- ⚠ **Reference-prompt length is the other big RTF lever AND the voice-quality
  lever** (`cfg.csm.ref_max_sec`, default 4 s). CSM re-encodes + re-prefills the
  conditioning prompt on EVERY sentence, so the built-in presets' ~10 s prompt
  pushed RTF to ~1.0 → audio "mashed up" (queue underrun). But too SHORT a prompt
  destabilizes the voice → **garbled/robotic** output. `CsmEngine._prompt_for`
  caps the prompt audio AND proportionally trims the transcript (both presets and
  clones — a mismatched text/audio pair garbles the voice) to `ref_max_sec`, and
  **caches the resulting `Segment` per voice** (cleared on clone/ref_text change),
  passed via `generate(context=[seg])`. 10 s→1.0, 5 s→~0.9, 4 s→~0.65, 3 s→~0.51
  on M5; **raise toward 5 s if the voice sounds robotic**, lower for more headroom.
- `SUPPORTED_VOICES` = 2 presets: `conversational_a` (female ★),
  `conversational_b` (male). Voice prompts auto-download from `sesame/csm-1b` on
  first use. **English-best** (multilingual presets are gone with Qwen).
- `Synthesizer(TTSConfig)` is a thin facade keeping the server surface
  (`synthesize`, `sample_rate`, `current_voice`, `swap_voice`, `load`,
  `reset_context`). `cfg.tts.engine` is a single-value enum (`"csm"`), extensible
  to a future `"miso"` (MisoTTS-8B port).
- ⚠ **No `speed` arg** (CSM's `generate()` has none) → the UI speed slider stays
  a no-op, same as Qwen was. `cfg.csm.speed` is kept inert for server/UI compat.
- ⚠ **Watermarking ON by default** — `generate()` applies a SilentCipher
  watermark (imperceptible, marks AI audio). Toggle off with `tts.csm.watermark:
  false` (the engine sets `model._watermarker = None`); kept on by default.
- ⚠ **Conversational context is single-segment only.** mlx-audio's public
  `generate()` conditions on `context[0]` when `voice_match=True`; the
  multi-segment (`voice_match=False`) branch is unusable in this version. So
  `reset_context()` is a no-op and `cfg.csm.context_turns` is reserved — true
  rolling multi-turn context needs the lower-level frame API (roadmap).

#### Reference-audio voice cloning (`tts.csm.clones`)

- Beyond the 2 presets, `config.yaml` can list cloned voices under
  `tts.csm.clones` (`CloneVoiceConfig`). Each appears in the UI picker as
  `clone:<name>`. CSM clones from the reference clip directly (no separate
  checkpoint, no reload) — the same loaded model takes `ref_audio` + `ref_text`.
- A clone entry: `name`, `wav` (reference clip), optional `label`, `ref_text`
  (clip transcript — auto-filled via **Parakeet, English-only** if omitted, so a
  non-English clip MUST set `ref_text` explicitly), and per-clone `temperature`.
  `CsmEngine._ref_for` returns `(expanded wav path, cached ref_text)`; the server
  resolves/caches `ref_text` off the MLX thread before synth (via
  `Transcriber.transcribe_clone_ref` → `ParakeetEngine.transcribe_file`).
  `ref_lang` is accepted for back-compat but ignored (Parakeet is English).
  ⚠ `instruct`/`speed` are Qwen-era fields —
  CSM **ignores** them (the clip sets timbre + prosody); kept for config
  back-compat.
- **Reference clips live in the project `voice/` folder.** `wav:` is resolved in
  `Config.load()`: a **relative** path (e.g. `voice/intro.wav`) is anchored to
  the **config file's directory** (not the launch CWD); absolute and `~/…` paths
  are left as written. So clones are portable regardless of where `readback`
  is started. `*.wav` is gitignored — clips stay local.
- **`scripts/make_clone_voice.sh`** prepares clips: re-encodes ANY audio/video
  (m4a/mp3/mp4/…) to the mono/24 kHz/16-bit PCM wav CSM can load (a renamed
  `.m4a` will NOT decode), optional `-s/-d` trim, `--batch` a folder. Default
  out-dir is the project `./voice`; it prints a ready-to-paste clones snippet.

### STT — Parakeet (stt/)

- `ASREngine` protocol (`stt/base.py`): `supported_models`, `current_model`,
  `load`, `swap_model`, `transcribe(audio, sr)`, `supports_streaming`. Shared
  `resample()` enforces the 16 kHz contract. `Transcriber` (transcriber.py) is a
  thin facade over the single engine: `current_engine`, `engines_available`
  (`("parakeet",)`), `models_for()`, `swap_engine` (only `"parakeet"` valid),
  `swap_model`, `streaming_engine()`. The facade/protocol is retained so adding a
  second engine later stays a one-file change.
- **ParakeetEngine** (`parakeet_engine.py`, sole engine): MLX/Metal.
  `transcribe()` is file/ffmpeg-only upstream, so we route BOTH batch and
  streaming through `transcribe_stream` + `add_audio(mx.array)`. Owns a
  **single-thread executor** (same MLX rule as CSM). `add_audio` underflows on
  <~100 ms chunks, so the engine buffers mic frames to `stream_chunk_ms` (320 ms)
  per encoder step. Streaming: `start_stream/feed/finalize/abort_stream`.
  `transcribe_file(path)` (loads via `mlx_audio.load_audio` → `transcribe`) backs
  clone-reference transcription. ~2.5 GB first download. **English-best** (v2);
  v3 covers 25 langs if selected.
- ⚠ **No hallucination guards** (unlike the removed Whisper) — Parakeet
  transcribes whatever audio it's fed. The server's `_is_phantom_utterance`
  filter + `_speaking` mic gate are what prevent echo/music self-trigger loops.

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
  `set_stt_engine {engine: "parakeet"}` (single-engine; kept for protocol
  stability), `set_stt_model {model}`,
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
  `vault`). Every chip opens Settings. The ASR control shows just the Parakeet
  model picker; the engine selector is gated on `sttEnginesAvailable.length > 1`,
  so with Parakeet as the sole engine it stays hidden (the two-level UI revives
  automatically if a second engine is added).
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
- Prefs key: `localStorage["readback.prefs.v10"]`. `loadPrefs()` chains legacy
  migrations (v9/v8); v10 adds `sttEngine`. Bump the key on any schema change.

## CLI

```
readback                                  # http://127.0.0.1:8000
readback --host 0.0.0.0 --port 8000       # LAN reachable (HTTP)
readback --host 0.0.0.0 --auto-cert       # LAN + auto self-signed cert; banner
                                           # prints SHA-256 fingerprint + /cert.pem URL
readback --host 0.0.0.0 --cert c.pem --key k.pem   # bring your own cert
readback --model nemotron3:33b            # override ollama.model for this run
readback --config /path/to/config.yaml    # custom config
```

Auto-cert: stored at `~/.readback/certs/{cert,key}.pem`, regenerated when
the detected LAN IP changes (tracked in `cert.meta.json`). Cert SAN includes
the LAN IP, `127.0.0.1`, and `localhost`. 825-day validity matches Safari's
trust ceiling.

## Voice options (CSM-1B)

`SUPPORTED_VOICES` (tts/csm_engine.py) = 2 preset voices, exposed via
`config.voices_available`:
- `conversational_a` ★ (female), `conversational_b` (male)

`swap_voice()` just sets `cfg.tts.csm.speaker` (per-call arg — instant; presets
and clones share one loaded model). CSM is **English-best** — the multilingual
Qwen speakers (Chinese `uncle_fu`, `ono_anna`, `sohee`) are gone.

Plus any **cloned voices** from `tts.csm.clones` (id `clone:<name>`) — reference
clips in the project `voice/` folder, prepped via `scripts/make_clone_voice.sh`.
See the cloning subsection under "TTS — CSM-1B" for the full picture.

## Latency budget (M5 — measured in P1/P4b)

| Stage | Value |
|---|---|
| VAD silence-end gate | ~480 ms (`vad.silence_end_ms`, config-tunable; was 750 ms) |
| Smart-Turn v3 decision | ~7–12 ms (CPU) |
| Parakeet streaming finalize | near-zero (most already streamed) |
| Parakeet batch (4.7s clip) | ~1.1 s cold / RTF ~0.24 |
| Nemotron-3-nano:4b first sentence | ~1.3 s cold (~200–500 ms warm) |
| CSM-1B first sentence | batch per sentence; **bf16** (MisoTTS-style, no quant) + 4 s prompt cap → realtime on M5 (F32 ~1.4 stalls; int8 was ~0.86 but garbled; raise ref toward 5 s for steadier timbre, lower for more headroom) |

Tool-call probes add one full Ollama non-streaming round-trip per hop
(usually 400–800 ms) before the final response streams. Three hops max.

## Echo / feedback handling

The web browser's `getUserMedia({ echoCancellation: true })` handles AEC, so
there's no PTT key, no RMS gate, no headphones requirement. AEC alone is not
enough on built-in MacBook speaker+mic (loud, non-linear echo close together),
so the **`_speaking` mic gate** (see Server pipeline) keeps the mic closed for
the full *playback* duration — not just until the bytes are sent — plus a
`SPEAKING_COOLDOWN_SEC` (0.6 s) reverb cooldown, which is what stops the
assistant hearing its own reply. Because Parakeet (unlike the removed Whisper)
has no hallucination guards, the **`_is_phantom_utterance` filter** (see Server
pipeline) is the second line of defense — it drops short backchannels the ASR
produces from any residual bleed/reverb/background-music during LISTENING.
⚠ Arbitrary background music (e.g. lyrics) can still be transcribed — the filter
only catches filler phrases; use headphones or stop other audio for clean runs.

## Install & verification

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch==2.4.0 torchaudio==2.4.0   # pinned; transformers<5 needs this torch
pip install -e .
pip install -e ".[wakeword]"             # optional; only if you re-enable the wake-word UI
cd readback/web/frontend && npm install && npm run build && cd ../../..
readback                                # boots; opens http://127.0.0.1:8000
```

**Dependency note:** `transformers` is pinned `<5`. mlx-audio declares
`transformers>=5.5`, but 5.x's import chain needs torch≥2.5
(`torch.distributed.tensor.device_mesh`); CSM-1B and Smart-Turn both run fine
on transformers 4.x with torch 2.4, so we override the pin.

First launch (weights download silently on first use):
1. Parakeet (~2.5 GB), CSM-1B (~6.2 GB) + its Mimi codec, Smart-Turn v3 (~8 MB).
   `nemotron-3-nano:4b` must be pulled in Ollama (`ollama pull nemotron-3-nano:4b`).
2. Open the page → orb breathes, "STANDBY" status.
3. Say "hello" → live partial caption appears → reply streams + speaks.
4. Settings → switch Parakeet model; switch voice (presets/clones).
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
- **First CSM-1B / Parakeet utterance is slow.** One-time MLX graph warm-up;
  `load()` pre-warms but the very first real synth/transcribe still pays some
  compile cost. Warm calls are faster. (CSM is a ~6.2 GB model — heavier cold
  start than the old 0.6 B Qwen.)
- **`<think>` leaks only on qwen3, not Nemotron.** `qwen3` (the LLM) ignores
  `think=False` and emits untagged reasoning prose — no stripper can catch
  untagged text. The default `nemotron-3-nano:4b` is clean. Pick a different
  model if it bothers you.
- **Speed slider does nothing on CSM-1B.** CSM's `generate()` has no `speed` arg.
  `cfg.csm.speed` is inert, kept only so the UI slider / config message stay
  wired (same no-op as Qwen was).
- **Cloned voices ignore `instruct`.** That was a Qwen voice-design hint; CSM
  takes timbre + prosody straight from the reference clip. The field is kept for
  config back-compat but has no effect.
- **MLX "no Stream(gpu, 0)" if you call Parakeet/CSM off their executor.** Both
  engines MUST run all model work on their own single-thread executor; never call
  the `_impl` methods or `mx` ops from another thread.

## Roadmap candidates (not committed)

- **MisoTTS-8B → MLX port.** Convert/quantize the 8B CSM-finetune (MisoLabs) to
  MLX and slot it into `cfg.tts.engine` as `"miso"` (the `Synthesizer` seam is
  ready). English-only, ~8B params — gate on measured M5 RTF; likely needs heavy
  quant to approach realtime.
- **True multi-turn CSM context.** mlx-audio's public `generate()` conditions on
  one segment only; drive the lower-level frame API to feed rolling conversation
  Segments (`cfg.csm.context_turns`) for cross-turn prosodic continuity.
- Round-trip persona/tools/inputMode/customPrompt prefs on reconnect (currently
  only sttModel/voice/speed are re-emitted in `App.tsx:78-100`).
- Wake-word download progress over WS.
- More search providers behind `WebSearchProvider` (Tavily, Brave).
- Long-term `memory.md` separate from session JSONL — explicit `remember(...)`
  tool, never auto-extracted.
- Wake-lock + PWA manifest for phone hands-free use.

## Version

Current: **v0.7.0** (Parakeet-only ASR — removed faster-whisper + the dual-engine
selector; added the phantom-utterance / speaker-bleed guard against echo/music
self-trigger loops; tuned end-of-turn gate to ~480 ms and CSM `ref_max_sec` to
3 s. CSM-1B TTS + Smart-Turn + Nemotron unchanged). Set in `pyproject.toml`,
`readback/__init__.py`, and `web/frontend/package.json`. Bump all three when
releasing. See [README.md#changelog](README.md#changelog) for release notes.
