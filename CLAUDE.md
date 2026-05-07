# local-tts — Project Context

A local voice conversation app similar to sesame.com, running entirely on-device.
Full voice loop: speak → STT → Ollama LLM → TTS → hear response.
Also supports text-in with voice-out mode.

## Hardware
- Apple M5 Pro, 48GB unified memory
- No CUDA. PyTorch MPS available, but **Kokoro runs faster on CPU** than MPS
  on this machine (iSTFT op falls back to CPU and transfer overhead dominates
  for an 82M-param model). Whisper also runs on CPU (CTranslate2 ARM NEON).

## Stack
- **LLM**: Ollama (already running locally, default model: `qwen3:8b`)
- **TTS**: Kokoro-82M (`hexgrad/Kokoro-82M`) — fast, near-human, runs on CPU
- **STT**: faster-whisper (`large-v3-turbo`, CPU int8 mode, CTranslate2 ARM NEON — no MPS backend exists)
- **Audio I/O**: sounddevice + webrtcvad-wheels
- **CLI/UI**: click + rich

## Architecture: 3-Thread Streaming Pipeline

```
[Thread 1: recorder]    mic → VAD → utterance → transcription_queue
[Thread 2: pipeline]    transcription_queue → Whisper → Ollama streaming
                        → sentence splitter → Kokoro TTS → playback_queue
[Thread 3: player]      playback_queue → sounddevice output

Text mode:              terminal input → pipeline_thread (skips recorder/Whisper)

Voice input modes (input.mode):
  - "ptt" (default): hold the configured key to record. Mic only captures
                     while held. PTT press during SPEAKING = interrupt + start
                     new recording. Default key is "alt_r" (right Option) —
                     pynput captures globally on macOS, so the key MUST NOT
                     be one used in normal typing (never "space"!).
  - "vad":           always-on, VAD-driven utterance detection. Interrupts use
                     the duration + RMS gate (see VAD section).
```

## Project Structure

```
local-tts/
├── pyproject.toml
├── config.yaml                  # user-editable defaults
│
└── local_tts/
    ├── cli.py                   # click: run, web, list-devices, download-models
    ├── app.py                   # ConversationApp: thread topology + queue wiring (CLI mode)
    ├── config.py                # Pydantic config loaded from config.yaml
    ├── state.py                 # AppState, Phase enum, shared threading events
    ├── audio/
    │   ├── recorder.py          # sounddevice InputStream + webrtcvad VAD loop
    │   └── player.py            # sounddevice playback, checks interrupt_event per chunk
    ├── stt/transcriber.py       # faster-whisper wrapper (CPU, int8)
    ├── llm/client.py            # ollama streaming + sentence boundary splitter
    ├── tts/synthesizer.py       # Kokoro KPipeline wrapper (CPU)
    ├── ui/display.py            # rich Live: conversation history + phase status (CLI)
    └── web/                     # browser UI (FastAPI + WebSocket)
        ├── server.py            # WS protocol, Session class, VAD-driven utterance segmentation
        └── static/
            ├── index.html       # sesame-style call interface
            ├── styles.css       # dark theme, animated orb
            ├── app.js           # WS client, mic capture, audio playback queue
            └── recorder.worklet.js  # AudioWorklet: mic → 16k Int16 PCM
```

## Critical Implementation Notes

### Kokoro TTS (tts/synthesizer.py)
- Use `kokoro.KPipeline(lang_code='a', device='cpu')` — CPU beats MPS on this 82M model
  because iSTFT (`aten::angle`) falls back to CPU and transfer overhead dominates.
- Default voice `af_heart`; other good options: `af_bella`, `af_sarah`, `am_michael`, `bf_emma`.
- KPipeline is stateless — no conversational context to manage (unlike CSM).
- First call downloads ~330MB model + voice pack from `hexgrad/Kokoro-82M`.
- Measured RTF on M5 Pro CPU: ~0.15× (≈500ms to synth a 3.4s sentence).

### Recorder (audio/recorder.py)
- 16kHz, blocksize=480 (30ms frames — matches webrtcvad requirement)
- Audio callback emits `(pcm_bytes, rms_float)` tuples to the recording loop.
- Two loop implementations selected by `input.mode`:

**PTT mode** (`_ptt_loop`, default):
- Mic frames are only accumulated while `_ptt_active` event is set.
- `ptt_press()` / `ptt_release()` are called from the pynput key listener
  in `app.py`. Press while phase==SPEAKING also fires `state.request_interrupt()`.
- On release, frames are submitted if duration ≥ `input.min_recording_ms`
  (default 200ms — filters out accidental key taps).
- No VAD analysis runs in this mode; the user defines utterance boundaries.

**VAD mode** (`_vad_continuous_loop`, legacy):
- 10 speech frames → SPEECH; 23 silence frames (~700ms) → finalize utterance
- **Interrupt during SPEAKING phase requires BOTH:**
  - sustained speech ≥ `vad.interrupt_speech_ms` (default 900ms / 30 frames), AND
  - per-frame RMS ≥ `vad.interrupt_rms_threshold` (default 0.05)
- The RMS gate filters out the AI's own playback bleeding from speaker → mic.
  Speaker bleed typically ~0.01–0.03 RMS; direct user speech ~0.05–0.20.
- Set `vad.allow_interrupt: false` to disable interrupts entirely.

### Keyboard listener (app.py::_start_key_listener)
- Single `pynput.keyboard.Listener` handles both PTT (press/release) and the
  F4 voice/text toggle.
- pynput captures keys GLOBALLY on macOS — events fire regardless of which
  app is focused. Therefore the PTT key MUST be one not used in normal
  typing. Default `alt_r` (right Option) is safe; `space` is catastrophic
  (every space typed anywhere on the system fires PTT and submits a brief
  mic snippet, which Whisper often hallucinates as "Yeah." or "Thanks for
  watching.").
- macOS requires Accessibility permission for the host process (Terminal,
  iTerm, etc.). Without it, pynput may silently drop events — PTT won't
  work and the run banner shows "This process is not trusted!". Grant via
  System Settings → Privacy & Security → Accessibility, then restart the
  terminal app.
- PTT is also gated by `state.get_mode() == VOICE` so the key is ignored
  in text mode.

### Sentence streaming (llm/client.py)
- Split on `.`, `!`, `?` followed by whitespace; min 8 chars per sentence
- System prompt: conversational, no markdown/bullets/special chars, 3-4 sentences max
- Trim conversation history to last 10 turns before each Ollama call
- `_strip_markdown` regex: `^[>#\-\*]+\s*` (NOT `^[\s>#\-\*]+`). The latter
  ate leading whitespace from per-token chunks like `" am"` → `"am"`, collapsing
  streamed output into `"Iamsorry"`. Keep the `\s` out of the character class.

### STT (stt/transcriber.py)
- `WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")` —
  distilled large-v3, near-large-v3 accuracy at ~the size and speed of
  `medium` (~1.6GB). Multilingual variant (no `.en`) is dramatically better
  on accented English. **faster-whisper / CTranslate2 has no MPS backend,
  so Whisper is CPU-only on Mac regardless of Apple GPU availability.**
  Sizes: tiny ~75MB, base ~150MB, small ~480MB, medium ~1.5GB,
  large-v3-turbo ~1.6GB, large-v3 ~3GB.
- `beam_size=10, best_of=10, patience=1.0` — wide beam search; runs
  comfortably on M-series CPU and the LLM step still dominates total
  latency.
- `no_speech_threshold=0.6, log_prob_threshold=-1.0,
  compression_ratio_threshold=2.4` — reject low-confidence segments as
  empty so faint speaker-bleed buffers stop hallucinating "Yeah." /
  "Thanks for watching."
- `temperature=[0.0, 0.2, ..., 1.0]` — explicit fallback schedule for
  low-confidence retries (this is faster-whisper's default; kept explicit
  so future tweaks are obvious).
- `condition_on_previous_text=False` — avoids hallucinating context bias
  from prior segments when audio is short.
- `vad_filter=True` suppresses Whisper's silence hallucinations.
- Module-level `warnings.filterwarnings("ignore", ..., RuntimeWarning)`
  silences faster-whisper's `mel_filters @ magnitudes` divide-by-zero /
  overflow / invalid-value warnings on near-silent buffers. The math
  produces NaN/-inf which Whisper handles internally; the warnings are noise.

## Install Sequence (order matters)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch==2.4.0 torchaudio==2.4.0
pip install -e .
local-tts download-models                          # whisper medium + Kokoro-82M (~1.6GB)
```

## Dependencies

```toml
"torch==2.4.0", "torchaudio==2.4.0",
"faster-whisper==1.2.1",
"ollama==0.6.2",
"sounddevice==0.5.5",
"numpy>=2.0.0,<3.0.0",
"webrtcvad-wheels==2.0.14",   # prebuilt ARM64 wheels
"click==8.1.8", "rich==15.0.0", "pynput==1.8.1",
"pydantic==2.13.3", "pyyaml>=6.0",
"kokoro>=0.9.4", "misaki[en]>=0.9.4", "soundfile>=0.12.1"
```

## CLI Commands

```
local-tts run [--model MODEL] [--text-mode] [--config path]
local-tts web [--host 127.0.0.1] [--port 8000] [--model MODEL]   # browser UI
local-tts list-devices        # show sounddevice input/output device indices
local-tts list-models         # show Ollama models available on configured host
local-tts download-models     # pre-download whisper + Kokoro models (~400MB)
local-tts test-tts "text"     # synthesize one sentence and play it (smoke test)
```

## Web mode (local_tts/web/)

`local-tts web` serves a sesame-style call interface in the browser. Why
this exists alongside the CLI:
- **Echo cancellation is free** — `getUserMedia({ echoCancellation: true })`
  uses the OS's AEC. No PTT key, no RMS gates, no headphones requirement.
- **No macOS Accessibility permission** needed — the browser handles input.
- **Cross-platform** (Mac, Linux, Windows, mobile) with no extra work.

WebSocket protocol (`/ws`):
- Client → server:
  - binary frames: Int16 PCM @ 16kHz, mono (mic audio)
  - JSON text frames: `{"type": "mute"|"unmute"|"interrupt"|"text_input", "text": "..."}`
- Server → client:
  - binary frames: Float32 PCM @ 24kHz, mono (TTS output)
  - JSON text frames: `phase`, `transcript {role: user|assistant}`, `level`,
    `config`, `error`

Server (`web/server.py::Session`):
- Accumulates incoming Int16 bytes, slices into 30ms frames for webrtcvad,
  segments utterances (8 frames speech start / 25 silence end / 12 minimum).
- `_run_pipeline(*, audio=None, text=None)` runs STT (skipped for text path)
  → LLM → Kokoro inside `asyncio.to_thread` so the event loop stays free.
- TTS audio is sent per-sentence as it becomes available so the client can
  start playback before the full response is generated.
- `interrupt` flag is `asyncio.Event` checked between sentences and is also
  set by a `text_input` arrival mid-response.

Frontend (`web/static/`):
- Vanilla JS, no framework. `recorder.worklet.js` is an AudioWorkletProcessor
  that downsamples mic input (device native, typically 48kHz) to 16kHz Int16
  chunks of ~60ms each. Playback uses `AudioBufferSourceNode` queued at
  `state.playbackTime` so chunks are gapless. An `AnalyserNode` drives the
  orb's `--scale` CSS variable for amplitude-reactive animation.
- AI captions accumulate sentence-by-sentence into `state.aiAccum`; reset on
  new user turn or Skip. Container is `max-height: 34vh` with overflow auto.
  A floating **Copy** button (`#copy-btn`) writes `state.aiAccum` to the
  clipboard; it is hidden until the first sentence arrives.
- Themed colors: every theme defines `--accent`, `--accent-dim`,
  `--accent-glow`, `--user`, `--ai-text`, plus 3-stop gradient + glow vars
  for each orb phase (idle / listen / think / speak). Body class
  `.theme-<name>` swaps everything. Current themes: **jarvis** (cyan) and
  **hacker** (green). The orb is a three.js point cloud rendered into
  `#brain-canvas` with a bloom postprocess pass — colors are pulled at
  runtime from `getComputedStyle(body).getPropertyValue("--accent")`.

UI controls:
- **Settings (gear icon, top-right)**: Microphone picker (lists all
  audioinputs via `enumerateDevices`, restarts capture with `{deviceId:
  {exact: id}}` on change, persists in `localStorage`); Theme swatches
  (jarvis cyan / hacker green); Orb size slider (120–380 px);
  Mic-meter and Captions toggles.
- **Dock pill (bottom)**: `[Mute · Skip · Type · Pause]`. Skip is enabled
  only while phase is `thinking` or `speaking`. **Pause** is a true
  pause/resume toggle (not "End call"): on click it stops the mic, drains
  the playback queue, sends `interrupt` to the server, freezes the call
  timer (`pauseTimer()` accumulates elapsed ms across pauses), forces the
  orb to `idle`, and disables the other dock buttons. The button icon swaps
  between two-bar pause and play-triangle resume; body class `.paused` and
  status `PAUSED` reflect the state. The WebSocket stays open — clicking
  Resume restarts the mic with the saved `prefs.micId` and reconnects
  `startTimer()` to the accumulated elapsed counter. `setPhase` is gated
  by `state.paused` so late server `phase` events don't clobber `PAUSED`.
- **Type popover**: Click "Type" → a pill-shaped input slides up from the
  dock pill (`position: absolute` anchored). Submitting sends `text_input`
  over WS, which bypasses STT. If pressed while AI is responding,
  `skipCurrent()` runs first so the new question takes over.
- **Mic meter**: 5 bars below the orb that bounce with the server's `level`
  events; live evidence the mic is picking you up.

Preferences (`localStorage` key `local-tts.prefs.v3`): `orbSize`,
`showMeter`, `showCaptions`, `theme` (`jarvis` | `hacker`), `micId`. Loaded
before connect; any saved `micId` that no longer exists falls back to
system default. Bump the version key when the prefs schema changes.

## Voice options (Kokoro)

Voice name = `{lang}{gender}_{name}`. The first letter MUST match `kokoro.lang_code`.

- American English (`lang_code: "a"`): `af_heart` ★, `af_bella` ★, `af_nicole`, `af_sarah`,
  `af_aoede`, `af_kore`, `af_nova`, `af_sky`, `am_michael`, `am_adam`, `am_echo`, `am_puck`
- British English (`lang_code: "b"`): `bf_emma`, `bf_isabella`, `bf_alice`, `bf_lily`,
  `bm_george`, `bm_lewis`, `bm_daniel`, `bm_fable`
- Other langs: Japanese `j*`, Mandarin `z*`, Spanish `e*`, French `f*`, Hindi `h*`,
  Italian `i*`, Portuguese `p*`

Best naturalness picks: **af_heart**, **af_bella**, **bf_emma**.

## Latency Budget (M5 Pro targets)

| Stage | Estimate |
|---|---|
| VAD silence detection | 700ms |
| Whisper large-v3-turbo @ beam_size=10 (5s audio) | ~700-1100ms |
| First LLM sentence | ~600-900ms |
| Kokoro synthesis of first sentence | ~300-500ms |
| **Total to first spoken word** | ~2.5-3 seconds |

If real-time feel matters more than transcription accuracy, drop Whisper
to `small` or `base` and `beam_size=1` in `stt/transcriber.py`.

## Verification Checklist

1. `local-tts list-devices` → correct mic and speaker shown
2. `local-tts download-models` → whisper + Kokoro download without error
3. `local-tts test-tts "hello"` → hear synthesized speech in current voice
4. `local-tts run --text-mode` → type "hello", hear spoken response
5. `local-tts run` (voice mode, PTT default) → hold SPACE, speak, release;
   transcription appears, response is spoken back
6. PTT during AI speech → press SPACE while AI talks, AI stops immediately
   and starts recording your new utterance
7. AI does NOT self-interrupt (PTT keeps mic muted while AI speaks)
8. F4 toggle → switch voice ↔ text mode, status bar updates
9. macOS Accessibility permission granted to terminal app (otherwise PTT silently fails)

## LLM model picks (latency vs quality)

Voice loop feels real-time when LLM first-token < ~400ms. Smaller is better:

| Model | First-token | Notes |
|---|---|---|
| `qwen3:1.7b` | ~150ms | Surprisingly capable for chit-chat |
| `qwen3:4b` | ~300ms | Best speed/quality balance |
| `llama3.2:3b` | ~250ms | Very natural conversation |
| `gemma3:4b` | ~300ms | Warm/conversational tone |
| `qwen3:8b` (default) | ~700–900ms | Best reasoning, noticeable wait |

Switch at runtime: `local-tts run --model qwen3:4b` (must `ollama pull` first).

## Echo / feedback handling

Acoustic feedback (speaker → mic → "user" speech) is the #1 source of bugs.
- **Best fix:** PTT mode (the default). Mic is muted unless the configured
  `input.ptt_key` is held (default `alt_r` — right Option), so the AI
  physically cannot trigger itself. Never set this to `space` (see PTT
  notes above).
- **Headphones:** eliminate the acoustic feedback path entirely. Useful with
  either input mode.
- **VAD mode mitigations:** the RMS gate in `audio/recorder.py` rejects quiet
  speaker bleed. Tune `vad.interrupt_rms_threshold` upward (e.g. 0.10) if AI
  still self-interrupts.
- **Last resort:** set `vad.allow_interrupt: false` (VAD mode only) to disable
  interrupts entirely.

Whisper hallucinations on near-silence (e.g. "of what you.", "Yeah.",
"Thanks for watching.") are a separate issue caused by the mic picking up
faint AI playback during LISTENING right after SPEAKING ends. Mitigations
already wired in `stt/transcriber.py`:
- `vad_filter=True, vad_parameters={"min_silence_duration_ms": 300}` —
  Whisper's internal VAD trims silent chunks before decoding.
- `no_speech_threshold=0.6` — drop a segment if the no-speech head is
  above this confidence.
- `log_prob_threshold=-1.0` — drop a segment whose average log-prob is
  below this (i.e. Whisper isn't confident in any of the tokens).
- `compression_ratio_threshold=2.4` — drop a segment whose token-stream
  compression ratio exceeds this (the classic "Thanks for watching"
  hallucination has very high repetition).
If you still see hallucinations, raise `no_speech_threshold` toward 0.7
or push `log_prob_threshold` up toward -0.7. Beyond that, the fix is
acoustic (headphones / lower playback volume).

## Roadmap / next iterations

These are the three tracks chosen for the next milestone (v0.3.0). When
adding code here, lean toward small, reversible changes that preserve the
two existing front-ends (CLI + web). Order is rough priority.

### 1. Tools / function-calling

Goal: let the assistant *do* things, not just answer. E.g. "what time is
it?", "add milk to my list", "search the web for X", "open the project
README".

- Ollama supports function calling via the `tools=[...]` param on
  `chat()` for tool-capable models (e.g. `qwen3`, `llama3.1`,
  `gemma3-tools`). Streaming + tools is supported but the streamed delta
  format includes `tool_calls` chunks that need handling alongside
  `content` chunks.
- New module: `local_tts/tools/` with a `Tool` protocol (`name`, `schema`,
  `run(args) -> str`) and a registry. Built-ins to start: `clock`,
  `web_search` (DuckDuckGo HTML, no API key), `file_read`,
  `note_append` (writes to a local JSONL).
- Pipeline change in `llm/client.py`: when a streamed tool_call is
  finalized, run the tool synchronously, append the result as a `tool`
  role message, and continue the stream. The sentence splitter must
  ignore the tool turn so it doesn't try to TTS the JSON.
- Voice/UX: speak a short "checking…" filler before tools that take
  >500ms so the user isn't staring at silence.
- Config: `tools.enabled: bool` (default false), `tools.allowed: [list]`
  (gate destructive ones).

### 2. Mobile-friendly web UI / PWA

Goal: open `https://<your-mac>:8000` from your phone on the same wifi
and have a usable call interface. Useful as a "walk around the room
hands-free" mode.

- Layout: orb shrinks to ~40vmin, dock pill becomes a thumb-reachable
  bottom row; settings panel becomes a full-screen sheet.
- iOS Safari needs a user gesture to start `AudioContext` — the existing
  click-to-start path covers this; verify that the WS-binary playback
  path also resumes correctly after the page is backgrounded
  (`audioCtx.state === "suspended"` → `resume()` on visibilitychange).
- HTTPS: phones won't grant `getUserMedia` on plain HTTP for non-localhost
  origins. Add a `--cert / --key` pair to `local-tts web` and document
  the `mkcert` flow, OR auto-generate a self-signed cert and surface the
  fingerprint so the user can trust it once.
- PWA: add `manifest.json` (icons, name, theme color synced to the active
  theme accent) + a minimal service worker that caches `/static/*` so
  the page loads offline once visited.
- Wake-lock: while a call is active, request `navigator.wakeLock.request("screen")`
  so the phone doesn't sleep mid-conversation.

### 3. Conversation memory / persistence

Goal: pick up a conversation across app restarts; optionally a long-term
"what does the assistant know about me" store separate from the rolling
turn buffer.

- Short-term: persist the last N turns to
  `~/.local-tts/sessions/<session-id>.jsonl`. New CLI flag
  `local-tts run --resume [session-id]`. Web UI: a "previous calls"
  drawer in the settings panel.
- Long-term: a separate `~/.local-tts/memory.md` file. The assistant gets
  a system-prompt slot for it; a small `remember(<fact>)` tool (see Tools
  track) appends to it. Keep it human-readable so the user can edit/redact.
- Privacy: never auto-extract memories from arbitrary turns — only write
  when the user explicitly says "remember that…" via the tool.
- Cap: rotate session JSONL files older than 30 days; cap memory.md at
  200 lines and prompt the user to prune when full.

## Version history

See [README.md#changelog](README.md#changelog) for user-facing release
notes. Current version: **v0.2.0** (web UI + Kokoro + STT tuning + Pause).

