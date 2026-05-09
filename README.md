# local-tts

A local, on-device voice assistant — speak (or type) to your local LLM and hear it talk back. Everything runs on your machine: no cloud calls, no API keys.

Sesame-style browser call interface with a 3D neural orb, hot-swappable voice and STT models, themes, captions, and a Pause control. The browser handles echo cancellation natively, so no PTT key or headphones are needed.

Built for Apple Silicon (M-series). Python 3.10+.

## Features

- 100% local pipeline — Ollama for the LLM, Kokoro-82M for TTS, faster-whisper for STT.
- Real-time conversation: streaming sentence-by-sentence playback so the assistant starts speaking before the full reply is generated.
- 20 Kokoro voices (American + British), hot-swappable from the UI.
- Six Whisper sizes from `tiny` to `large-v3`, hot-swappable from the UI.
- Three themes (Jarvis cyan / Hacker green / Amber).

## Quick start

Requires macOS on Apple Silicon, Python 3.10+, and [Ollama](https://ollama.ai/).

```bash
# 1. Start Ollama and pull a chat model
ollama serve &                          # or launch the Ollama desktop app
ollama pull qwen3:4b                  # default; any chat model works

# 2. Clone & install
git clone git@github.com:MKS-01/local-tts.git
cd local-tts
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch==2.4.0 torchaudio==2.4.0
pip install -e .

# 3. Launch
local-tts                               # http://127.0.0.1:8000
```

No HuggingFace login needed — speech models download automatically on first run (~1.8 GB: Whisper medium + Kokoro-82M).

## Usage

```bash
local-tts                               # http://127.0.0.1:8000
local-tts --host 0.0.0.0 --port 8080
local-tts --model qwen3:4b
```

Open the URL, click anywhere to unlock audio, then speak.

**Dock controls (bottom):**

- **Mute** — toggle the mic. The server stops processing your audio.
- **Skip** — interrupt the current AI response.
- **Type** — open a text input that bypasses STT but still streams a voice reply. If used mid-response, it interrupts the AI first.
- **Pause / Resume** — true pause: stops the mic, drains playback, freezes the call timer; click again to pick up where you left off.

**Settings (gear icon, in dock):** opens a centered floating panel.

- **Microphone** — every input device the browser exposes.
- **Voice** — Kokoro TTS voice (`af_heart`, `af_bella`, `bf_emma`, `am_michael`, …). Hot-swappable while idle.
- **Speech recognition** — Whisper STT model. Hot-swappable while idle.
- **Theme** — Jarvis (cyan / scanning-eye icon), Hacker (green / terminal icon), or Amber (sun icon).
- **Orb size**, **Mic meter**, **Captions** toggles.

All preferences persist in `localStorage`.

## Configuration

Edit `config.yaml` for non-UI knobs:

| Key | What | Default |
|---|---|---|
| `ollama.model` | Any local Ollama chat model | `qwen3:4b` |
| `kokoro.voice` | TTS voice (full list in [CLAUDE.md](CLAUDE.md)) | `af_bella` |
| `whisper.model` | `tiny` / `base` / `small` / `medium` / `large-v3-turbo` / `large-v3` | `medium` |
| `whisper.beam_size` | 5 = balanced, 10 = max accuracy (+200–400 ms) | `5` |
| `vad.aggressiveness` | WebRTC VAD aggressiveness 0–3 | `2` |

> **Picking a Whisper model.** On Apple Silicon CPU (faster-whisper has no MPS backend), the encoder dominates and "distilled" models aren't always faster than `medium`. Rough latency on a 5-second utterance: `medium` ≈ 500–800 ms, `large-v3-turbo` ≈ 700–1100 ms, `large-v3` ≈ 1500–2500 ms. Drop to `small` or `base` for sub-300 ms STT.

## How it works

The browser streams 16 kHz Int16 PCM over a WebSocket. The server runs VAD to segment utterances, transcribes with Whisper, streams the response from Ollama sentence-by-sentence, synthesizes each sentence with Kokoro, and sends Float32 PCM back to the browser for gapless playback.

```
browser mic → WebSocket (Int16 PCM) → VAD → Whisper → Ollama (stream)
           → sentence splitter → Kokoro → WebSocket (Float32 PCM) → browser speaker
```

See [CLAUDE.md](CLAUDE.md) for deeper architectural notes (interrupt handling, hot-swap locking, VAD tuning).

## Latency on M5 Pro CPU

Indicative — varies with the LLM and utterance length.

| Stage | Estimate |
|---|---|
| Whisper `medium` (5 s audio, beam_size 5) | ~500–800 ms |
| First LLM sentence (`qwen3:4b`) | ~300 ms |
| Kokoro synthesis of first sentence | ~300–500 ms |
| **Total to first spoken word** | **~1.5–2.5 s** |

## Changelog

- **v0.3.1** — Settings panel redesigned as a centered floating modal; theme picker uses per-theme SVG icons (eye / terminal / sun) instead of colored dots.
- **v0.3.0** — Web-only: removed CLI/PTT/terminal interfaces; simplified to a single `local-tts` command.
- **v0.2.0** — Web UI (FastAPI + WebSocket), Kokoro-82M TTS (~10× faster than CSM-1B on Apple Silicon), voice/STT/theme pickers, Pause control.
- **v0.1.0** — Initial CLI release: VAD-driven voice loop, Whisper + Ollama + CSM-1B, 3-thread streaming pipeline.

## License

MIT — see [LICENSE](LICENSE).
