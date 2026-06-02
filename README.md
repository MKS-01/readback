# vox-tinker

> A local-first **voice-agent playground** — talk or type to a local LLM, hear it talk back, and shape *who* answers: swap personas on the fly, clone any voice from a short clip, and hot-swap the ASR / LLM / TTS models live. No cloud, no API keys, nothing leaves your machine. Every conversation can also auto-file itself into your Obsidian vault.

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

Most "local AI voice" projects are a CLI loop, a thin wrapper around a cloud STT/TTS API, or need an NVIDIA GPU. This is a browser app where every model runs on your Apple Silicon machine, and the pipeline **streams end-to-end**: Parakeet transcribes live as you speak, Smart-Turn decides when you're actually done, Ollama generates, and Qwen3-TTS speaks each sentence as it arrives — so the reply *starts playing before it's fully generated* (~2.5 s to first word). Browser WebRTC echo cancellation means no headphones, no push-to-talk; HTTPS over LAN means you can use it from a phone.

---

## Make it your own

vox-tinker is a *playground*, not a fixed assistant — the point is to configure **who** answers and **how**:

- **Personas, swappable live.** Five seeds — `default` (sharp & tech-savvy), `concise`, `researcher` (answer-first, cites specifics), `chef` (veg-leaning Indian home cooking), `professor` (a witty AI/ML lecturer) — plus a `custom` slot you edit from the browser. Each is just a system prompt; add your own in `config.py`. Swaps are atomic (an in-flight reply finishes on its original prompt).
- **Voice cloning.** Beyond the 9 built-in Qwen3-TTS speakers, clone *any* voice from a ~10–15 s clip. `scripts/make_clone_voice.sh` preps the audio; register it under `tts.qwen.clones` and it shows up as `clone:<name>`. Works cross-lingual (a Hindi clip can read English replies); tune delivery per clone via `instruct` / `speed` / `temperature`.
- **Hot-swap the whole stack.** ASR engine + model, LLM model, voice, persona, and speed all change from Settings — no restart.
- **Bring any model.** Any chat model pulled in Ollama works; the default is NVIDIA's `nemotron-3-nano:4b`.

---

## Tech stack

| Layer | Technology |
|---|---|
| **LLM** | [Ollama](https://ollama.ai/) — default `nemotron-3-nano:4b` (`think=False`); any local chat model, with function-calling / tools |
| **STT** | **Dual engine:** [Parakeet](https://github.com/senstella/parakeet-mlx) (MLX, default, streaming) + [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (batch, 6 sizes) |
| **Turn-taking** | [Smart-Turn v3](https://github.com/pipecat-ai/smart-turn) — semantic end-of-turn (ONNX/CPU) over webrtcvad; VAD-only fallback |
| **TTS** | [Qwen3-TTS-0.6B](https://github.com/QwenLM/Qwen3-TTS) via [mlx-audio](https://github.com/Blaizzy/mlx-audio) — Metal, 24 kHz, 9 speakers + clones |
| **Server / UI** | [FastAPI](https://fastapi.tiangolo.com/) + WebSocket · React + TypeScript + Vite + zustand · three.js orb, AudioWorklet capture |
| **Extras** | Obsidian markdown export · DuckDuckGo web search (no key) · optional [openWakeWord](https://github.com/dscripka/openWakeWord) |

---

## Quick start

Requires macOS on Apple Silicon, Python 3.10+, and [Ollama](https://ollama.ai/).

```bash
# 1. Start Ollama and pull a chat model
ollama serve &                          # or launch the Ollama desktop app
ollama pull nemotron-3-nano:4b          # default; any chat model works

# 2. Clone & install
git clone git@github.com:MKS-01/vox-tinker.git
cd vox-tinker
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch==2.4.0 torchaudio==2.4.0
pip install -e .

# 3. Build the React frontend (one-time; rerun after frontend edits)
cd vox_tinker/web/frontend && npm install && npm run build && cd ../../..

# 4. Launch
vox-tinker                              # http://127.0.0.1:8000
```

Speech models download automatically on first run (Parakeet ~2.5 GB, Qwen3-TTS-0.6B, Smart-Turn ~8 MB). No HuggingFace login needed.

---

## Using it

A single browser page — no Electron. Five header chips (`voice` · `model` · `persona` · `tools` · `vault`) show live state; tap any to open Settings. The orb breathes when idle and lights up while speaking; captions stream the transcript live (`LISTENING_` → `PROCESSING ···` → reply).

**Dock:** Mute · Skip (interrupt mid-reply) · Type (text input, still gets a voice reply) · Pause/Resume · Settings.

**Settings — everything changes without a restart:**

- **ASR** — Parakeet (default, streams live captions) ↔ Whisper (batch); the model picker filters to the active engine. Parakeet `…-v2` ★ / `-v3` (25 langs) / `-1.1b`; Whisper `tiny` → `large-v3`. *Whisper's multilingual checkpoints handle heavy accents better — switch when you need that.*
- **LLM / Voice / Persona / Speed** — voice, persona, and cloning are covered in [Make it your own](#make-it-your-own); LLM is any pulled Ollama model.
- **Tools** — master toggle plus per-tool checkboxes.
- Mic device, orb size, and mic-meter / captions toggles.

Prefs persist in `localStorage` (`vox-tinker.prefs.v10`); STT engine/model, voice, and speed round-trip back to the server on reconnect.

---

## Second brain (optional)

Tools ship **on** in the bundled `config.yaml`; Obsidian export ships **off** (opt-in). Flip either `enabled` flag to change it.

**Obsidian export** — set `obsidian.enabled: true`, then each session is written as a topic-filed markdown transcript at disconnect (the folder name is chosen by the LLM), with YAML frontmatter plus the full turn-by-turn body. In-progress sessions are mirrored to crash-recovery JSONL under `~/.vox-tinker/sessions/` and deleted once the markdown commits.

```yaml
obsidian:
  enabled: true
  vault_root: ~/Documents/Obsidian/vox-tinker   # any path, ~ expanded
```

**Tools** — with `tools.enabled: true`, the LLM can call `clock` and `web_search` (DuckDuckGo, no API key) and fold the results into its reply. Tool round-trips stay out of the spoken stream — you hear the answer, not the planning. The search provider is swappable (Tavily / Brave) behind one interface.

---

## Cross-device access (phone / tablet)

Browsers block the mic on plain HTTP for non-localhost origins, so use HTTPS over LAN:

```bash
vox-tinker --host 0.0.0.0 --auto-cert     # banner prints the URL + cert fingerprint + /cert.pem link
# …or bring your own cert (e.g. mkcert):
vox-tinker --host 0.0.0.0 --cert cert.pem --key key.pem
```

Trust the auto-cert once per device — **iOS:** open `/cert.pem` → install profile → Certificate Trust Settings → toggle on · **Android:** install as CA cert · **macOS:** Keychain Access → Always Trust. The cert is stored in `~/.vox-tinker/certs/` and regenerated if your LAN IP changes.

---

## Configuration

UI-switchable settings persist on their own; edit `config.yaml` for the rest:

| Key | What | Default |
|---|---|---|
| `ollama.model` | Any local Ollama chat model | `nemotron-3-nano:4b` |
| `stt.engine` | ASR engine: `parakeet` or `whisper` | `parakeet` |
| `stt.parakeet.model` / `stt.whisper.model` | Per-engine checkpoint | `…parakeet-tdt-0.6b-v2` / `medium` |
| `tts.qwen.speaker` | Qwen3-TTS speaker (9 presets) | `ryan` |
| `tts.qwen.clones` | Cloned voices (`name`, `wav`, `instruct`, …) | — |
| `turn.enabled` / `turn.threshold` | Smart-Turn end-of-turn (VAD-only fallback if off) | `true` / `0.5` |
| `vad.aggressiveness` | WebRTC VAD aggressiveness 0–3 | `2` |
| `persona.active` / `persona.personas` | Active persona + overrides | `default` / (5 seeded) |
| `tools.enabled` / `tools.allowed` | Function-calling switch + allowlist | `true` / `[clock, web_search]` |
| `obsidian.enabled` / `obsidian.vault_root` | Markdown export (opt-in) + vault path | `false` / `~/Documents/Obsidian/vox-tinker` |
| `memory.session_dir` / `memory.keep_days` | Crash-recovery JSONL location + rotation | `~/.vox-tinker/sessions` / `30` |

---

## How it works

```
browser mic → WebSocket (Int16 PCM 16kHz)
  → webrtcvad utterance segmentation
  → Parakeet STT (streaming → live partials)   [or Whisper, batch]
  → Smart-Turn v3 confirms end-of-turn (else keep listening)
  → Ollama streaming LLM (think=False) ⇄ (tools, when enabled)
  → sentence splitter → Qwen3-TTS (per sentence)
  → WebSocket (Float32 PCM 24kHz) → browser speaker (gapless queue)
  → (on disconnect) topic classifier → Obsidian markdown export
```

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the system-level view (streaming cascade, threading model, turn lifecycle, extension points) and **[CLAUDE.md](CLAUDE.md)** for implementation notes (MLX single-thread executors, interrupt handling, hot-swap locking, Whisper hallucination guards).

---

## Changelog

**v0.5.0 — Open-model voice pipeline.** Dual ASR (Parakeet streaming default + Whisper batch, switchable); Smart-Turn v3 semantic end-of-turn over webrtcvad; Nemotron default with `<think>` stripping; Qwen3-TTS (replaces Kokoro) with 9 speakers + reference-clip cloning; live partial captions.

**v0.4.0 — Second brain.** Obsidian topic-filed markdown export; `clock` + `web_search` tools; runtime persona switching (5 seeds + custom); React + Vite + TypeScript frontend.

**v0.3.0 — Web UI overhaul.** Single Ghost theme, simplified header, borderless captions.

*Deferred:* wake-word listening — backend is in place (`vox_tinker/wakeword/`, `[wakeword]` extra) but the UI is hidden until a Picovoice Porcupine backend lands for fast custom keywords.

---

## License

MIT — see [LICENSE](LICENSE).
