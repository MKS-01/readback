# local-tts

A local, on-device voice assistant — speak (or type) to your local LLM and hear it talk back. Two front-ends:

- **Web UI** (`local-tts web`) — sesame-style call interface in the browser with a 3D "neural orb", themes, voice + microphone pickers, captions, and a Pause control. **Recommended** — the browser handles echo cancellation natively, so no PTT key or headphones are needed.
- **CLI** (`local-tts run`) — push-to-talk loop in the terminal with a `rich` UI.

Built for Apple Silicon (M-series). No cloud calls, no API keys — only Ollama running locally and a one-time download of the speech models.

## Stack

- **LLM**: [Ollama](https://ollama.ai/) (any local model — default `qwen3:8b`)
- **TTS**: [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) — fast, near-human voices, runs on CPU
- **STT**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) `large-v3-turbo` (CPU int8 via CTranslate2 ARM NEON — Apple GPU/MPS is not used; no MPS backend exists in faster-whisper)
- **Audio**: sounddevice + webrtcvad-wheels (CLI) / `getUserMedia` + `AudioWorklet` (web)
- **CLI UI**: click + rich
- **Web UI**: FastAPI + WebSocket, vanilla JS, three.js for the orb

> Why Kokoro over CSM-1B? On Apple Silicon, Kokoro is ~10× faster (RTF ≈ 0.15× on M5 Pro CPU), is stateless, and produces equally natural English voices.

## Architecture

A 3-thread streaming pipeline overlaps LLM generation, TTS synthesis, and audio playback so the assistant starts speaking as soon as the first sentence is ready:

```
[recorder]   mic → VAD/PTT → utterance → transcription_queue
[pipeline]   transcription_queue → Whisper → Ollama (stream)
             → sentence splitter → Kokoro TTS → playback_queue
[player]     playback_queue → speaker  (checks interrupt_event per chunk)
```

Voice input has two modes (set in `config.yaml: input.mode`):

- **`ptt`** (default) — hold the configured key (`alt_r` / right Option by default) to record. Pressing PTT while the AI is speaking interrupts it and starts recording your next utterance. The default key is deliberately not `space`, since `pynput` captures keys globally on macOS.
- **`vad`** — always-on. Utterance boundaries are detected by webrtcvad. A duration + RMS gate suppresses self-interruption from speaker bleed.

Text mode skips the recorder/Whisper stages entirely — typed input flows straight into the pipeline.

The web UI uses an alternate pipeline where the browser handles echo cancellation natively (`getUserMedia({ echoCancellation: true })`), so PTT and RMS gates aren't needed.

## Setup

Requirements: macOS on Apple Silicon, Python 3.10–3.12, [Ollama](https://ollama.ai/) running locally with at least one model pulled.

```bash
# 1. Make sure Ollama is running and a model is available
ollama serve &                          # or launch the Ollama desktop app
ollama pull qwen3:8b                    # default; any chat model works

# 2. Clone and enter
git clone git@github.com:MKS-01/local-tts.git
cd local-tts

# 3. Python env
python3.11 -m venv .venv
source .venv/bin/activate

# 4. Install (PyTorch first so the right wheel is picked)
pip install torch==2.4.0 torchaudio==2.4.0
pip install -e .

# 5. Pre-download model weights (~1.9GB: Whisper large-v3-turbo + Kokoro-82M + voice pack)
local-tts download-models

# 6. Launch the web UI
local-tts web                           # open http://127.0.0.1:8000
```

No HuggingFace login is required — both speech models are public. If you'd rather start in the terminal, jump to the [CLI section](#cli).

## Usage

### Web UI (recommended)

```bash
local-tts web                            # http://127.0.0.1:8000
local-tts web --host 0.0.0.0 --port 8080
local-tts web --model qwen3:4b
```

Open the URL in any modern browser. Click into the page so the browser unblocks audio, then start speaking — browser-native echo cancellation means no PTT key, no RMS gates, no headphones requirement.

The dock pill at the bottom has four controls:

- **Mute** — toggle the mic. Server stops processing your audio.
- **Skip** — interrupt the current AI response (only enabled while it's thinking/speaking).
- **Type** — open a text-input popover; submitting bypasses STT but you still hear a voice response. Triggered mid-response, it interrupts the AI first.
- **Pause / Resume** — true pause: stops the mic, drains playback, interrupts the AI, freezes the call timer, and disables the other controls. Click again to pick up where you left off.

The gear icon (top-right) opens settings:

- **Microphone** — every input device the browser exposes; persists to `localStorage`.
- **Voice** — the Kokoro TTS voice (20 American + British options like `af_heart`, `af_bella`, `bf_emma`, `am_michael`, …). Hot-swappable while idle.
- **Speech recognition** — Whisper STT model: `tiny` / `base` / `small` / `medium` / `large-v3-turbo` / `large-v3`. Hot-swappable while idle.
- **Theme** — labeled cards for **Jarvis** (cyan), **Hacker** (green), **Amber** (warm orange). The orb's color follows.
- **Orb size**, **Mic meter** and **Captions** toggles.

All preferences persist in `localStorage` and are re-applied on every page load.

> **Picking a Whisper model.** On Apple Silicon CPU (faster-whisper has no MPS backend), the encoder dominates and "distilled" models aren't always faster than `medium`. Pick by latency target — `medium` ≈ 500–800ms, `large-v3-turbo` ≈ 500–900ms, `large-v3` ≈ 1500–2500ms. The accompanying `whisper.beam_size` (default `5`) lets you trade ±200–400ms for accuracy.

### CLI

```bash
# Voice mode (PTT — hold right Option to talk)
local-tts run

# Text mode (type questions, hear responses)
local-tts run --text-mode

# Override Ollama model
local-tts run --model qwen3:4b

# Utilities
local-tts list-devices                  # audio device indices
local-tts list-models                   # Ollama models
local-tts test-tts "hello world"        # one-shot TTS smoke test
```

In-app controls:

- **Hold `alt_r`** (right Option) — push-to-talk. Press while the AI is speaking to interrupt and re-record.
- **F4** — toggle voice ↔ text mode.
- **Ctrl+C** — quit.

> macOS: grant **Accessibility** permission to your terminal app (System Settings → Privacy & Security → Accessibility), otherwise PTT key events are silently dropped.

## Configuration

Edit `config.yaml` to change Ollama model & system prompt, Kokoro voice, Whisper size, VAD sensitivity, PTT key, audio devices, and more. Notable knobs:

- `kokoro.voice` — `af_heart`, `af_bella`, `af_sarah`, `am_michael`, `bf_emma` and others (full list in `CLAUDE.md`).
- `whisper.model` — `tiny` / `base` / `small` / `medium` / `large-v3-turbo` / `large-v3`. `large-v3-turbo` is the default — distilled large-v3, similar size to `medium` but much closer to large-v3 accuracy. Drop to `small` or `base` if you want lower latency.
- `input.mode` — `"ptt"` or `"vad"`.
- `input.ptt_key` — any `pynput` key name. **Never use `space`** — it would fire on every space typed system-wide.

## Latency budget (M5 Pro)

| Stage | Estimate |
|---|---|
| VAD silence detect / PTT release | ~200–700 ms |
| Whisper `large-v3-turbo` @ beam_size=5 (5s audio) | ~500–900 ms |
| Whisper `medium` @ beam_size=5 (5s audio)         | ~500–800 ms |
| Whisper `small` @ beam_size=5 (5s audio)          | ~300–500 ms |
| First LLM sentence (qwen3:4b) | ~300 ms |
| Kokoro synthesis of first sentence | ~300–500 ms |
| **Total to first spoken word** | ~1.5–3 s depending on LLM |

## Changelog

### v0.2.0 — Web UI + Kokoro + STT tuning

**TTS — switched from CSM-1B to Kokoro-82M**
- ~10× faster on Apple Silicon (RTF ≈ 0.15× on M5 Pro CPU vs ≈1.5× for CSM).
- Stateless — no conversational context to manage between calls.
- Smaller cache footprint (~330MB vs ~6.8GB), no HuggingFace login required.
- New voices: `af_heart`, `af_bella`, `af_sarah`, `am_michael`, `bf_emma`, ...

**STT — tuned for accuracy on accented English**
- Default model bumped from `base.en` → `large-v3-turbo` (distilled large-v3, ~1.6GB).
- `beam_size` 5 → 10, `best_of` 5 → 10, `patience=1.0` for wider beam search.
- Added hallucination guards: `no_speech_threshold=0.6`, `log_prob_threshold=-1.0`, `compression_ratio_threshold=2.4` — silent / faint speaker-bleed buffers now drop to empty instead of producing "Yeah." or "Thanks for watching."
- Explicit fallback temperature schedule for low-confidence retries.

**Voice input — push-to-talk added (now the default)**
- `input.mode: ptt` — hold the configured key (`alt_r` / right Option by default) to record. PTT during AI speech interrupts and records the next utterance.
- Old always-on VAD mode is still available via `input.mode: vad`.
- PTT key is deliberately **not** `space` — `pynput` captures keys globally on macOS and `space` would fire on every space typed system-wide.

**New: Web UI (`local-tts web`)**
- Sesame-style call interface in the browser, served by FastAPI + WebSocket.
- Browser-native echo cancellation (`getUserMedia({ echoCancellation: true })`) — no PTT or RMS gates needed.
- 3D animated "neural orb" rendered with three.js + bloom postprocess, color-driven by the active theme.
- Themes: **Jarvis** (cyan) and **Hacker** (green) — swap from the settings panel.
- Settings panel: microphone picker (lists all `audioinput` devices, persists to `localStorage`), orb size, mic-meter and captions toggles.
- Dock pill controls: **Mute · Skip · Type · Pause**.
  - **Pause** is a real pause/resume — stops mic, drains playback, interrupts the AI, freezes the call timer; click again to pick up where you left off. WebSocket stays open.
  - **Skip** interrupts the current AI response without ending the call.
  - **Type** opens a popover input that bypasses STT but still streams a voice response.
- Live captions for both user input and AI response, with a Copy button on the AI side.
- Mic meter (5 bars) reflects server-side mic level so you have evidence the input is reaching the pipeline.

**Other**
- `local-tts test-tts "text"` smoke-test command for one-shot synthesis.
- LLM history trimmed to last 10 turns before each Ollama call to keep context bounded.
- Markdown stripping in the streaming sentence splitter (`^[>#\-\*]+\s*`) — fixed a bug where the broader pattern collapsed streamed token whitespace.

### v0.1.0 — initial release

- CLI voice loop with always-on VAD: mic → faster-whisper → Ollama (streaming) → CSM-1B → speaker.
- Text mode (F4 to toggle).
- 3-thread streaming pipeline (recorder / pipeline / player).

## License

MIT — see [LICENSE](LICENSE).

