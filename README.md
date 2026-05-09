# local-tts

> 100% local voice assistant — speak (or type) to your LLM, hear it talk back. No cloud, no API keys.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Apple_Silicon-black?style=flat-square&logo=apple&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)
![Local](https://img.shields.io/badge/Runs-100%25_Local-6366f1?style=flat-square)

## Tech stack

| Layer | Technology |
|---|---|
| **LLM** | [Ollama](https://ollama.ai/) — any local chat model (`qwen3`, `llama3.2`, `gemma3`, …) |
| **TTS** | [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) — 20 voices, ~300 ms synthesis on CPU |
| **STT** | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — 6 sizes (`tiny` → `large-v3`), hot-swappable |
| **Server** | [FastAPI](https://fastapi.tiangolo.com/) + WebSocket — streams audio sentence-by-sentence |
| **Frontend** | Vanilla JS + AudioWorklet — 3D neural orb via three.js, no framework |
| **Audio I/O** | sounddevice + WebRTC VAD |

## Features

- Real-time streaming — the assistant starts speaking before the full reply is generated.
- 20 Kokoro voices (American + British), hot-swappable from the UI.
- Six Whisper sizes from `tiny` to `large-v3`, hot-swappable from the UI.
- Three themes: Jarvis (cyan), Hacker (green), Amber.
- Browser echo cancellation — no PTT key or headphones required.

## Quick start

Requires macOS on Apple Silicon, Python 3.10+, and [Ollama](https://ollama.ai/).

```bash
# 1. Start Ollama and pull a chat model
ollama serve &                          # or launch the Ollama desktop app
ollama pull qwen3:4b                    # default; any chat model works

# 2. Clone & install
git clone git@github.com:MKS-01/local-tts.git
cd local-tts
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch==2.4.0 torchaudio==2.4.0
pip install -e .

# 3. Launch
local-tts                               # http://127.0.0.1:8000
```

Speech models download automatically on first run (~1.8 GB: Whisper medium + Kokoro-82M). No HuggingFace login needed.

## Cross-device access (phone / tablet)

Browsers block microphone access on plain HTTP for any non-localhost origin. Use `--auto-cert` to generate a self-signed TLS cert and serve over HTTPS:

```bash
local-tts --host 0.0.0.0 --auto-cert
```

The startup banner prints:
- The **network URL** to open on other devices (`https://<your-mac-ip>:8000`)
- The **SHA-256 fingerprint** to verify the cert in your browser
- A **`/cert.pem` download link** to trust on iOS / Android / macOS

**Trusting the cert on each platform:**

| Device | Steps |
|---|---|
| **iOS** | Open `/cert.pem` link → Settings → General → VPN & Device Management → install → Certificate Trust Settings → toggle on |
| **Android** | Open `/cert.pem` link → install as CA certificate (Settings › Security › Install from storage) |
| **macOS** | Open `/cert.pem` → double-click downloaded file → Keychain Access → set to Always Trust |

The cert is stored in `~/.local-tts/certs/` and reused across restarts. It is regenerated automatically if your LAN IP changes.

To use your own cert instead (e.g. from `mkcert`):

```bash
local-tts --host 0.0.0.0 --cert cert.pem --key key.pem
```

## Usage

```bash
local-tts                               # http://127.0.0.1:8000
local-tts --host 0.0.0.0 --port 8080
local-tts --model qwen3:4b
```

Open the URL, click anywhere to unlock audio, then speak.

**Dock controls (bottom):**

- **Mute** — toggle the mic.
- **Skip** — interrupt the current AI response.
- **Type** — text input that bypasses STT but still streams a voice reply. Interrupts the AI if mid-response.
- **Pause / Resume** — stops the mic, drains playback, and freezes the call timer. Click again to resume.

**Settings (gear icon, in dock):** opens a floating panel.

- **Microphone** — every input device the browser exposes.
- **Voice** — Kokoro TTS voice (`af_heart`, `af_bella`, `bf_emma`, `am_michael`, …). Hot-swappable while idle.
- **Speech recognition** — Whisper STT model. Hot-swappable while idle.
- **Theme** — Jarvis (cyan / eye icon), Hacker (green / terminal icon), or Amber (sun icon).
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

> **Picking a Whisper model.** On Apple Silicon CPU (faster-whisper has no MPS backend), the encoder dominates. Rough latency on a 5-second utterance: `medium` ≈ 500–800 ms, `large-v3-turbo` ≈ 700–1100 ms. Drop to `small` or `base` for sub-300 ms STT.

## How it works

The browser streams 16 kHz Int16 PCM over a WebSocket. The server runs VAD to segment utterances, transcribes with Whisper, streams the response from Ollama sentence-by-sentence, synthesizes each sentence with Kokoro, and sends Float32 PCM back to the browser for gapless playback.

```
browser mic → WebSocket (Int16 PCM) → VAD → Whisper → Ollama (stream)
           → sentence splitter → Kokoro → WebSocket (Float32 PCM) → browser speaker
```

See [CLAUDE.md](CLAUDE.md) for deeper architectural notes (interrupt handling, hot-swap locking, VAD tuning).

## Changelog

- **v0.3.1** — `--auto-cert` / `--cert` / `--key` flags for HTTPS cross-device access; `/cert.pem` download endpoint for iOS/Android trust flow; settings panel redesigned as a centered floating modal; theme picker uses per-theme SVG icons.
- **v0.3.0** — Web-only: removed CLI/PTT/terminal interfaces; simplified to a single `local-tts` command.
- **v0.2.0** — Web UI (FastAPI + WebSocket), Kokoro-82M TTS (~10× faster than CSM-1B on Apple Silicon), voice/STT/theme pickers, Pause control.
- **v0.1.0** — Initial CLI release: VAD-driven voice loop, Whisper + Ollama + CSM-1B, 3-thread streaming pipeline.

## License

MIT — see [LICENSE](LICENSE).
