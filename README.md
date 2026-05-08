# local-tts

A local, on-device voice assistant — speak (or type) to your local LLM and hear it talk back. Everything runs on your machine.

- **Web UI** (`local-tts web`) — sesame-style call interface in the browser, with a 3D "neural orb", hot-swappable voice and STT models, themes, captions, and a Pause control. **Recommended** — the browser handles echo cancellation natively, so no PTT key or headphones are needed.
- **CLI** (`local-tts run`) — push-to-talk voice loop in the terminal.

Built for Apple Silicon (M-series). No cloud calls, no API keys.

## Features

- 100% local pipeline — Ollama for the LLM, Kokoro-82M for TTS, faster-whisper for STT.
- Real-time conversation: streaming sentence-by-sentence playback so the assistant starts speaking before the full reply is generated.
- 20 Kokoro voices (American + British), hot-swappable from the UI.
- Six Whisper sizes from `tiny` to `large-v3`, hot-swappable from the UI.
- Three themes (Jarvis cyan / Hacker green / Amber).
- Two front-ends sharing one pipeline: browser UI and terminal CLI.

## Quick start

Requires macOS on Apple Silicon, Python 3.10+, and [Ollama](https://ollama.ai/).

```bash
# 1. Start Ollama and pull a chat model
ollama serve &                          # or launch the Ollama desktop app
ollama pull qwen3:8b                    # default; any chat model works

# 2. Clone & install
git clone git@github.com:MKS-01/local-tts.git
cd local-tts
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch==2.4.0 torchaudio==2.4.0
pip install -e .

# 3. Pre-download speech models (~1.8GB: Whisper medium + Kokoro-82M)
local-tts download-models

# 4. Launch
local-tts web                           # http://127.0.0.1:8000
```

No HuggingFace login needed — both speech models are public.

## Usage

### Web UI

```bash
local-tts web                           # http://127.0.0.1:8000
local-tts web --host 0.0.0.0 --port 8080
local-tts web --model qwen3:4b
```

Open the URL, click anywhere to unlock audio, then speak.

**Dock controls (bottom):**

- **Mute** — toggle the mic. The server stops processing your audio.
- **Skip** — interrupt the current AI response.
- **Type** — open a text input that bypasses STT but still streams a voice reply. If used mid-response, it interrupts the AI first.
- **Pause / Resume** — true pause: stops the mic, drains playback, freezes the call timer; click again to pick up where you left off.

**Settings (gear icon, top-right):**

- **Microphone** — every input device the browser exposes.
- **Voice** — Kokoro TTS voice (`af_heart`, `af_bella`, `bf_emma`, `am_michael`, …). Hot-swappable while idle.
- **Speech recognition** — Whisper STT model. Hot-swappable while idle.
- **Theme** — Jarvis (cyan), Hacker (green), or Amber.
- **Orb size**, **Mic meter**, **Captions** toggles.

All preferences persist in `localStorage`.

### CLI

```bash
local-tts run                           # voice mode (PTT)
local-tts run --text-mode               # text-in, voice-out
local-tts run --model qwen3:4b          # override Ollama model

local-tts list-devices                  # audio device indices
local-tts list-models                   # available Ollama models
local-tts test-tts "hello world"        # one-shot TTS smoke test
```

In-app: hold **`alt_r`** (right Option) for push-to-talk, **F4** to toggle voice/text, **Ctrl+C** to quit.

> **macOS:** grant **Accessibility** permission to your terminal app (System Settings → Privacy & Security → Accessibility), otherwise PTT key events are silently dropped.

## Configuration

Edit `config.yaml` for non-UI knobs:

| Key | What | Default |
|---|---|---|
| `ollama.model` | Any local Ollama chat model | `qwen3:8b` |
| `kokoro.voice` | TTS voice (full list in [CLAUDE.md](CLAUDE.md)) | `af_heart` |
| `whisper.model` | `tiny` / `base` / `small` / `medium` / `large-v3-turbo` / `large-v3` | `medium` |
| `whisper.beam_size` | 5 = balanced, 10 = max accuracy (+200–400 ms) | `5` |
| `input.mode` | `ptt` (push-to-talk) or `vad` (always-on) | `ptt` |
| `input.ptt_key` | Any [pynput](https://pynput.readthedocs.io/) key — **never use `space`** (it captures globally on macOS) | `alt_r` |

> **Picking a Whisper model.** On Apple Silicon CPU (faster-whisper has no MPS backend), the encoder dominates and "distilled" models aren't always faster than `medium`. Rough latency on a 5-second utterance: `medium` ≈ 500–800 ms, `large-v3-turbo` ≈ 700–1100 ms, `large-v3` ≈ 1500–2500 ms. Drop to `small` or `base` for sub-300 ms STT.

## How it works

A 3-thread streaming pipeline overlaps LLM generation, TTS synthesis, and audio playback so the assistant starts speaking as soon as the first sentence is ready.

```
[recorder]  mic → VAD/PTT → utterance → transcription_queue
[pipeline]  transcription_queue → Whisper → Ollama (stream)
            → sentence splitter → Kokoro → playback_queue
[player]    playback_queue → speaker  (interruptible per chunk)
```

The web UI replaces the recorder/player with a WebSocket and lets the browser handle echo cancellation. See [CLAUDE.md](CLAUDE.md) for deeper architectural notes (interrupt handling, hot-swap locking, VAD tuning).

## Latency on M5 Pro CPU

Indicative — varies with the LLM and utterance length.

| Stage | Estimate |
|---|---|
| Whisper `medium` (5 s audio, beam_size 5) | ~500–800 ms |
| First LLM sentence (`qwen3:4b`) | ~300 ms |
| Kokoro synthesis of first sentence | ~300–500 ms |
| **Total to first spoken word** | **~1.5–2.5 s** |

## Releases

- **v0.2.0** — Web UI (FastAPI + WebSocket), Kokoro-82M TTS (~10× faster than CSM-1B on Apple Silicon), push-to-talk default, voice/STT/theme pickers, Pause control.
- **v0.1.0** — Initial CLI release: VAD-driven voice loop, Whisper + Ollama + CSM-1B, 3-thread streaming pipeline, text mode toggle.

## License

MIT — see [LICENSE](LICENSE).
