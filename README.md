# local-tts

> A fully local voice assistant — speak or type to your LLM, hear it talk back. No cloud. No API keys. No data leaves your machine.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Apple_Silicon-black?style=flat-square&logo=apple&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)
![Local](https://img.shields.io/badge/Runs-100%25_Local-6366f1?style=flat-square)

---

<p align="center">
  <img src="screenshots/screenshot-one.png" width="48%" alt="Main interface" />
  &nbsp;
  <img src="screenshots/screenshot-two.png" width="48%" alt="Settings panel" />
</p>

---

## Why this is different

Most "local AI voice" projects are either a CLI loop with no real UI, a thin wrapper around a cloud STT/TTS API, or require expensive GPU hardware. This project is none of those.

| | local-tts | Typical local voice project |
|---|---|---|
| **UI** | Browser — 3D neural orb, live captions, one-click settings | Terminal / CLI |
| **Cloud dependency** | None — every model runs on-device | STT or TTS calls an API |
| **Hardware** | Apple Silicon, 24 GB+ unified memory (tested: M5 Pro 48 GB) | Often requires NVIDIA GPU |
| **First word latency** | ~2.5 s end-to-end | 3–8 s (round-trip to cloud) |
| **Voice / model switching** | Hot-swap in the UI, no restart | Config file edit + restart |
| **Cross-device** | Phone + tablet over LAN via HTTPS | Localhost only |
| **Echo cancellation** | Browser WebRTC AEC — no headphones needed | PTT key or headphones required |

The pipeline is a 3-thread streaming design: Whisper transcribes while Ollama generates, and Kokoro synthesizes each sentence as it arrives — so the assistant **starts speaking before the full reply is generated**.

---

## Tech stack

| Layer | Technology |
|---|---|
| **LLM** | [Ollama](https://ollama.ai/) — any local chat model (`qwen3`, `llama3.2`, `gemma3`, …) |
| **TTS** | [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) — 20 voices, ~300 ms synthesis on CPU |
| **STT** | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — 6 sizes (`tiny` → `large-v3`), hot-swappable |
| **Server** | [FastAPI](https://fastapi.tiangolo.com/) + WebSocket — streams audio sentence-by-sentence |
| **Frontend** | Vanilla JS + AudioWorklet — 3D neural orb via three.js, no framework |
| **Audio I/O** | sounddevice + WebRTC VAD |

---

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

---

## Interface

The UI is a single browser page — no Electron, no desktop app. Open `http://127.0.0.1:8000` after launching.

**Orb** — a three.js point-cloud that reacts to phase: dim and breathing when idle, bright and active when speaking. Ghost theme: matte white/grey, no colored glow.

**Live captions** — the INPUT label animates to `LISTENING_` (blinking cursor) while waiting and `PROCESSING ···` (dot reveal) while the LLM is thinking. The AI response streams in sentence by sentence.

**Dock controls (bottom bar):**

| Button | What it does |
|---|---|
| **Mute** | Toggle mic on/off |
| **Skip** | Interrupt the current AI response immediately |
| **Type** | Slide-up text input — bypasses STT, still gets a voice reply |
| **Pause / Resume** | Freeze everything (mic, playback, timer) — WebSocket stays open |
| **⚙ Settings** | Open the settings panel |

### Settings panel — model & voice switching

The settings panel lets you change every runtime parameter **without restarting the server**:

- **Microphone** — switch between any input device the browser sees; new device activates instantly.
- **Speech Recognition (STT model)** — swap between six Whisper checkpoints while idle:
  - `tiny` (~75 MB) — fastest, ~150 ms, light accuracy
  - `base` (~150 MB) — good for clear speech
  - `small` (~480 MB) — solid balance
  - `medium` (~1.5 GB, **default**) — 500–800 ms, recommended
  - `large-v3-turbo` (~1.6 GB) — best for accented speech
  - `large-v3` (~3 GB) — maximum accuracy, slower
  - The dropdown disables while the new model loads; re-enables on server confirmation.
- **LLM Model** — switch between any model currently pulled in Ollama. Change takes effect on the next message.
- **Voice (TTS)** — 20 Kokoro voices, switchable while idle. Best picks:
  - `af_bella` ★ — warm American female (default)
  - `af_heart` ★ — expressive American female
  - `bf_emma` ★ — natural British female
  - `am_michael` — clear American male
  - Full list: `af_*` (American female), `am_*` (American male), `bf_*` / `bm_*` (British)
- **Speech Speed** — Slow / Medium / Fast, applied to every TTS synthesis call.
- **Orb size** — 120–380 px slider.
- **Mic meter / Captions** — toggle the 5-bar input meter and live transcript display.

All preferences persist in `localStorage` and restore on next page load.

---

## Cross-device access (phone / tablet)

Browsers block microphone access on plain HTTP for non-localhost origins. Use `--auto-cert` for HTTPS over LAN:

```bash
local-tts --host 0.0.0.0 --auto-cert
```

The startup banner prints the network URL, SHA-256 cert fingerprint, and a `/cert.pem` download link.

**Trust the cert:**

| Device | Steps |
|---|---|
| **iOS** | Open `/cert.pem` → Settings → General → VPN & Device Management → install → Certificate Trust Settings → toggle on |
| **Android** | Open `/cert.pem` → install as CA certificate (Settings › Security › Install from storage) |
| **macOS** | Download `/cert.pem` → Keychain Access → set to Always Trust |

Cert stored in `~/.local-tts/certs/`, reused across restarts, regenerated if your LAN IP changes.

To use your own cert (e.g. from `mkcert`):

```bash
local-tts --host 0.0.0.0 --cert cert.pem --key key.pem
```

---

## Configuration

Edit `config.yaml` for non-UI knobs:

| Key | What | Default |
|---|---|---|
| `ollama.model` | Any local Ollama chat model | `qwen3:4b` |
| `kokoro.voice` | TTS voice (full list in [CLAUDE.md](CLAUDE.md)) | `af_bella` |
| `whisper.model` | STT checkpoint | `medium` |
| `whisper.beam_size` | 5 = balanced, 10 = max accuracy (+200–400 ms) | `5` |
| `vad.aggressiveness` | WebRTC VAD aggressiveness 0–3 | `2` |

> **Picking a model for speed.** On Apple Silicon CPU, `medium` lands at 500–800 ms for a 5-second utterance. Drop to `small` for sub-300 ms. `large-v3-turbo` is only marginally faster than `large-v3` on CPU — the "6× faster" claim is GPU-bound.

---

## How it works

```
browser mic → WebSocket (Int16 PCM 16kHz)
  → VAD utterance segmentation
  → Whisper STT
  → Ollama streaming LLM
  → sentence splitter
  → Kokoro TTS (per sentence)
  → WebSocket (Float32 PCM 24kHz)
  → browser speaker (gapless AudioBufferSourceNode queue)
```

The pipeline is **streaming end-to-end**: Kokoro synthesizes each sentence the moment it arrives from Ollama, so playback starts ~2.5 s after you stop speaking — well before the full reply is generated.

See [CLAUDE.md](CLAUDE.md) for deeper notes on interrupt handling, hot-swap locking, VAD tuning, and Whisper hallucination mitigations.

---

## License

MIT — see [LICENSE](LICENSE).
