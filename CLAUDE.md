# local-tts — Project Context

A local voice + text assistant with a browser UI. Speak or type → STT → Ollama
LLM (with optional tools) → Kokoro TTS → playback. Optional second-brain layer
auto-files every conversation as a markdown transcript in an Obsidian vault.

This project is **web-only**. The CLI is one command (`local-tts`) that boots
a FastAPI server and serves a React UI; there is no terminal conversation mode,
no PTT, no `click`/`rich`. If you see references to `cli.py`, `app.py`,
`audio/recorder.py`, `ui/display.py`, or `pynput` in older docs/PRs, that
codebase is gone.

## Hardware

- Apple M5 Pro, 48 GB unified memory (primary target).
- No CUDA. PyTorch MPS is available, but **Kokoro runs faster on CPU** than MPS
  on this machine — iSTFT (`aten::angle`) falls back to CPU and transfer
  overhead dominates for an 82M-param model.
- Whisper is CPU-only on Mac regardless (faster-whisper / CTranslate2 has no
  MPS backend; ARM NEON int8 is the fast path).

## Stack

- **LLM**: Ollama, default `qwen3:4b` (config.yaml). Tool-capable models
  (`qwen3`, `llama3.1`, `gemma3-tools`) are required when `tools.enabled: true`.
- **TTS**: Kokoro-82M (`hexgrad/Kokoro-82M`) on CPU; 20-voice curated picker.
- **STT**: faster-whisper, 6-size hot-swappable picker (`tiny` → `large-v3`),
  default `medium`, int8 CPU.
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
├── pyproject.toml             # v0.4.0; [wakeword] extras for openwakeword + onnxruntime
├── config.yaml                # user-editable; all v0.4 features on by default
├── README.md                  # user-facing; mirror for changelog
│
└── local_tts/
    ├── __main__.py            # `local-tts` entry: argparse, optional --auto-cert/--cert/--key,
    │                          # uvicorn boot, banner with TLS fingerprint
    ├── config.py              # Pydantic config; load() drops unknown top-level keys + migrates
    │                          # legacy `ollama.system_prompt` into the "default" persona
    │
    ├── llm/client.py          # LLMClient: Ollama streaming, sentence splitter,
    │                          # persona snapshot, tool-call probe loop
    ├── stt/transcriber.py     # faster-whisper wrapper, swap_model() under threading.Lock,
    │                          # SUPPORTED_MODELS allowlist
    ├── tts/synthesizer.py     # Kokoro KPipeline wrapper, swap_voice() under threading.Lock,
    │                          # SUPPORTED_VOICES curated picker (20 voices)
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

- Single `Session` per WebSocket connection. No threads: STT/LLM/TTS each run
  inside `asyncio.to_thread` so the event loop stays free for the audio fan-in
  + control messages.
- LLM streaming runs in a producer **thread** (not coroutine) that pushes
  finished sentences onto an `asyncio.Queue` via `loop.call_soon_threadsafe`.
  The consumer races each `queue.get()` against an `interrupt_event` so Skip
  takes effect mid-sentence without waiting for Ollama to finish.
- Mic frames are dropped entirely while `pipeline_task is not None`. This is
  the only mechanism that prevents speaker bleed from triggering the wake-word
  detector or VAD — there is no separate "muted-during-playback" flag and no
  300 ms grace tail. If a future change splits the pipeline so audio is
  accepted during speaking, **this gate must be replaced** or the wake-word
  detector will self-fire on every reply.
- Utterance segmentation: 8 speech frames to start (~240 ms), 25 silence
  frames to end (~750 ms), 12-frame minimum (~360 ms — drops noise blips).

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

### Kokoro TTS (tts/synthesizer.py)

- `KPipeline(lang_code='a', device='cpu')` — CPU beats MPS on this 82 M model
  because iSTFT (`aten::angle`) falls back to CPU and transfer overhead
  dominates. Don't switch this without re-benchmarking.
- First call downloads ~330 MB model + voice pack from `hexgrad/Kokoro-82M`.
- Voice name format: `{lang}{gender}_{name}`. First letter MUST match
  `lang_code` — so switching between American (`a`) and British (`b`) voices
  rebuilds the pipeline. `swap_voice()` is locked.
- Measured RTF on M5 Pro CPU: ~0.15× (≈500 ms to synth a 3.4 s sentence).
- `SUPPORTED_VOICES` is a curated tuple of `(id, label)` pairs (20 voices)
  exposed via the WS `config.voices_available` payload.

### STT (stt/transcriber.py)

- `WhisperModel("medium", device="cpu", compute_type="int8")` default.
  faster-whisper / CTranslate2 has no MPS backend — Whisper is CPU-only.
- Sizes (int8): tiny ~75 MB, base ~150 MB, small ~480 MB, medium ~1.5 GB,
  large-v3-turbo ~1.6 GB, large-v3 ~3 GB.
- Runtime picker: `Transcriber.swap_model(name)` hot-swaps under a
  `threading.Lock`. `transcribe()` reads `self.model` under a single atomic
  load so an in-flight call finishes against the old weights — no half-swap.
- `beam_size` default 5 (balanced); 10 = max accuracy at +200–400 ms.
  `best_of` mirrors `beam_size`. `patience=1.0` is hardcoded.
- Hallucination guards (silence-bleed):
  `no_speech_threshold=0.6`, `log_prob_threshold=-1.0`,
  `compression_ratio_threshold=2.4`, `condition_on_previous_text=False`,
  `vad_filter=True, vad_parameters={"min_silence_duration_ms": 300}`.
  If you still see "Yeah." / "Thanks for watching." artifacts, raise
  `no_speech_threshold` toward 0.7 or `log_prob_threshold` toward -0.7.
- Module-level `warnings.filterwarnings("ignore", ..., RuntimeWarning)`
  silences faster-whisper's `mel_filters @ magnitudes` divide-by-zero noise
  on near-silent buffers.

### Sentence streaming (llm/client.py)

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
  `set_stt_model {model}`, `set_model {model}` (Ollama LLM swap),
  `set_speed {speed}`, `set_persona {name}`, `set_persona_custom_prompt {prompt}`,
  `set_input_mode {mode: "vad"|"wake_word"}`, `set_tools_enabled {value: bool}`,
  `set_tool_allowed {tool, value: bool}`.

Server → client:
- Binary: raw Float32 PCM @ 24 kHz mono (TTS output).
- JSON: `phase {value}`, `transcript {role, text, session_id}`, `level {value}`,
  `config {session_id, voice, voices_available, model, models_available, stt_model,
  stt_models_available, speed, persona, personas_available, tools_enabled,
  tools_available, tools_allowed, input_mode, wakeword_model, obsidian_enabled}`,
  `error {message}`, `stt_model {state: loading|ready|error, model, message?}`,
  `voice {state, voice, message?}`, `model {state, model}`,
  `persona {state, name, personas_available?, message?}`,
  `input_mode {value, state?, message?}`,
  `tools_enabled {value}`, `tools_allowed {value}`.

### Reconnect behavior (App.tsx config-message handler)

The `config` payload arrives on every connect and re-seeds the store. The
client then **only** re-emits saved prefs for `sttModel`, `voice`, and `speed`
that diverge from server defaults. Persona / tools-enabled / inputMode /
customPrompt are received from the server but **not** sent back on reconnect —
those mirror `config.yaml` on each fresh connection. If you change this, also
update the README (the prior version of the docs claimed all of these
round-trip and it was incorrect).

## Frontend (web/frontend/)

- React 18 functional components, single `App.tsx` orchestrator. The audio
  engine, WS client, and three.js brain controller live OUTSIDE the React
  tree as singletons; they push events into a zustand store, so React
  re-renders never tear down the socket or audio context.
- Header is five clickable chips (`voice` · `model` · `persona` · `tools` ·
  `vault`). Every chip opens Settings — no separate "open settings"
  affordance is necessary. (A sixth `mode` chip for VAD / wake-word is
  retained in the wake-word deferral notes but currently not rendered.)
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
- Prefs key: `localStorage["local-tts.prefs.v9"]`. v8→v9 migration runs once
  in `loadPrefs()` and adds `persona`, `customPersonaPrompt`, `inputMode`,
  `toolsEnabled`. Bump the version key whenever the prefs schema changes.

## CLI

```
local-tts                                  # http://127.0.0.1:8000
local-tts --host 0.0.0.0 --port 8000       # LAN reachable (HTTP)
local-tts --host 0.0.0.0 --auto-cert       # LAN + auto self-signed cert; banner
                                           # prints SHA-256 fingerprint + /cert.pem URL
local-tts --host 0.0.0.0 --cert c.pem --key k.pem   # bring your own cert
local-tts --model qwen3:1.7b               # override ollama.model for this run
local-tts --config /path/to/config.yaml    # custom config
```

Auto-cert: stored at `~/.local-tts/certs/{cert,key}.pem`, regenerated when
the detected LAN IP changes (tracked in `cert.meta.json`). Cert SAN includes
the LAN IP, `127.0.0.1`, and `localhost`. 825-day validity matches Safari's
trust ceiling.

## Voice options (Kokoro)

Voice name = `{lang}{gender}_{name}`. The first letter MUST match
`kokoro.lang_code`.

- American English (`lang_code: "a"`): `af_heart` ★, `af_bella` ★, `af_nicole`,
  `af_sarah`, `af_aoede`, `af_kore`, `af_nova`, `af_sky`, `am_michael`,
  `am_adam`, `am_echo`, `am_puck`
- British English (`lang_code: "b"`): `bf_emma` ★, `bf_isabella`, `bf_alice`,
  `bf_lily`, `bm_george`, `bm_lewis`, `bm_daniel`, `bm_fable`
- Other langs: Japanese `j*`, Mandarin `z*`, Spanish `e*`, French `f*`,
  Hindi `h*`, Italian `i*`, Portuguese `p*` (none in `SUPPORTED_VOICES`).

Best naturalness picks: **af_heart**, **af_bella**, **bf_emma**.

## Latency budget (M5 Pro targets)

| Stage | Estimate |
|---|---|
| VAD silence-end detection | ~750 ms |
| Whisper large-v3-turbo @ beam=5 (5s audio) | ~500–900 ms |
| Whisper medium @ beam=5 (5s audio) | ~500–800 ms |
| Whisper small @ beam=5 (5s audio) | ~300–500 ms |
| First LLM sentence (qwen3:4b) | ~300–600 ms |
| Kokoro synthesis of first sentence | ~300–500 ms |
| **Total to first spoken word** | ~2.5–3 s |

Tool-call probes add one full Ollama non-streaming round-trip per hop
(usually 400–800 ms) before the final response streams. Three hops max.

## Echo / feedback handling

The web browser's `getUserMedia({ echoCancellation: true })` handles AEC, so
there's no PTT key, no RMS gate, no headphones requirement. Hallucination
guards in `stt/transcriber.py` (see STT section above) handle the residual
"AI bleed picked up during LISTENING" case where Whisper would otherwise
emit "Yeah." or "Thanks for watching." on a near-silent buffer.

## Install & verification

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch==2.4.0 torchaudio==2.4.0
pip install -e .
pip install -e ".[wakeword]"             # optional; only needed if you re-enable the wake-word UI
cd local_tts/web/frontend && npm install && npm run build && cd ../../..
local-tts                                # boots; opens http://127.0.0.1:8000
```

First launch:
1. Whisper `medium` (~1.5 GB) + Kokoro-82M voice pack download silently.
2. Open the page → orb breathes, "STANDBY" status.
3. Say "hello" → orb scales to listening → "ANALYZING" → reply streams.
4. (Tools on) Say "what time is it" → log shows `tool_call: clock -> N chars`.
5. (Obsidian on) Have a 2+ turn convo, close tab → markdown lands at
   `~/Documents/Obsidian/local-tts/<topic-slug>/YYYY-MM-DD--<6hex>.md`.
6. (Wake-word) UI hidden by default; see Wake-word section to re-enable.

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

## Roadmap candidates (not committed)

- Round-trip persona/tools/inputMode/customPrompt prefs on reconnect (currently
  only sttModel/voice/speed are re-emitted in `App.tsx:78-100`).
- Wake-word download progress over WS.
- More search providers behind `WebSearchProvider` (Tavily, Brave).
- Long-term `memory.md` separate from session JSONL — explicit `remember(...)`
  tool, never auto-extracted.
- Wake-lock + PWA manifest for phone hands-free use.

## Version

Current: **v0.4.0** (Second-brain). Set in `pyproject.toml` and
`local_tts/__init__.py`. Bump both when releasing. See
[README.md#changelog](README.md#changelog) for user-facing release notes.
