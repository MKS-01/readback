# readback

> Paste an article URL, get it read aloud in a natural voice — or a spoken summary of it. Fetch → extract → (optional LLM summary) → on-device neural TTS → listen in the browser or download the audio. Fully local. No cloud, no API keys, nothing leaves your machine.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Apple_Silicon-black?style=flat-square&logo=apple&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)
![Local](https://img.shields.io/badge/Runs-100%25_Local-6366f1?style=flat-square)

---

## What it does

1. **Paste a URL.** readback fetches the page and extracts the clean article text (no nav, ads, or boilerplate).
2. **Pick a mode.** *Full article* reads the text verbatim; *Summary* has a local LLM turn it into a tight spoken explanation first.
3. **Listen.** The text is synthesized offline with **CSM-1B** (Sesame's neural speech model) and played in a minimalist browser player — or downloaded as a WAV. In Summary mode you can also reveal and copy the spoken text.

Everything runs on-device on Apple Silicon. The only model that touches the network is whatever you've already pulled into Ollama locally.

---

## Why offline synthesis

readback grew out of a real-time voice assistant, but reading a long article is a different problem: there's **no live conversation to keep up with**, so there's no reason to fight for real-time latency. Instead it synthesizes the **whole piece up front**, trims and paces the audio, then hands back one gapless file. That removes the audio-underrun and echo problems of streaming TTS entirely, and lets the voice quality lean toward "clean" over "fast."

---

## Tech stack

| Layer | Technology |
|---|---|
| **Article extraction** | [trafilatura](https://trafilatura.readthedocs.io/) — URL → clean text, with a browser-UA fetch fallback for sites that 403 the default agent |
| **Summary (optional)** | [Ollama](https://ollama.ai/) — default **`nemotron-3-nano:4b`** (`think=False`, `<think>` stripped); any pulled chat model works |
| **TTS** | [CSM-1B](https://huggingface.co/senstella/csm-1b-mlx) (Sesame Conversational Speech Model) via [csm-mlx](https://github.com/senstella/csm-mlx) — MLX/Metal, 24 kHz, bf16 |
| **Voices** | 2 built-in reading voices + **clone any voice from a short reference clip**; optional **LoRA fine-tuning** |
| **Server** | [FastAPI](https://fastapi.tiangolo.com/) + WebSocket — streams fetch/summarize/synthesis progress, serves the finished WAV |
| **Frontend** | React 18 + TypeScript + Vite + zustand — three.js point-cloud orb, custom audio player, dark "Ghost" theme |

---

## Quick start

Requires macOS on Apple Silicon, Python 3.10–3.12, and [Ollama](https://ollama.ai/).

```bash
# 1. Start Ollama and pull a chat model (only used for Summary mode)
ollama serve &                          # or launch the Ollama desktop app
ollama pull nemotron-3-nano:4b          # default; any chat model works

# 2. Clone & install
git clone git@github.com:MKS-01/readback.git
cd readback
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .

# 3. Build the React frontend (one-time; rerun after editing readback/web/frontend/)
cd readback/web/frontend && npm install && npm run build && cd ../../..

# 4. Launch
readback                                # http://127.0.0.1:8000
```

The CSM-1B weights (~6 GB) download from Hugging Face on first synthesis — no login needed. You can also run without installing via `python -m readback`.

---

## Using it

Open `http://127.0.0.1:8000`:

- **Paste an article URL** and hit the **→** button (or Enter).
- Toggle **Full article** / **Summary**, pick a **Voice**.
- While it works, the orb takes over the screen with the current phase (*Fetching… / Summarizing… / Synthesizing N/M*) and a **Cancel** button.
- When it's done you get the article title, a **custom audio player** (play/pause, scrubber, duration), and **↓ Download audio**.
- In **Summary** mode, **Show transcript** reveals the spoken summary text with a **Copy** button.

The header shows the active **model** and connection state. The orb is a three.js point cloud that animates while working and while playing.

---

## Voices

readback's voice comes from a short **reference clip** that CSM conditions on — the clip's timbre, age, and accent are what you hear. Two paths:

**Built-in reading voices** — `conversational_a` / `conversational_b`, conditioned on Sesame's read-speech prompts for an even, literary reading tone. English-best.

**Clone a voice** — drop a clean 5–8 s mono clip into `voice/` and register it under `tts.csm.voices`:

```yaml
tts:
  csm:
    speaker: "kay"          # default voice = the name below
    temperature: 0.6        # delivery: lower = composed, higher = livelier
    voices:
      - name: "kay"
        label: "Kay ★"
        wav: "voice/k.wav"          # relative to config.yaml
        speaker: 0
        ref_text: "Exact transcript of the clip."   # MUST match the audio
```

`ref_text` **must** be the clip's exact transcript — a mismatched pair garbles the voice. `temperature` tunes *delivery*, not *who* it sounds like; that's fixed by the clip. The bundled config ships a sample `kay` voice so it works out of the box. See `.claude/skills/csm-voice` for the full clone/tune procedure.

**Fine-tune (optional)** — for higher fidelity with more audio (minutes per speaker), there's a LoRA pipeline under [`finetune/`](finetune/README.md); point `tts.csm.lora_path` at the trained adapter.

---

## Cross-device access (phone / tablet)

The reader works over plain HTTP, but to open it from another device on your LAN use `--auto-cert` for HTTPS:

```bash
readback --host 0.0.0.0 --auto-cert
```

The startup banner prints the network URL, the SHA-256 cert fingerprint, and a `/cert.pem` download link. Trust the cert once per device (iOS: Settings → General → VPN & Device Management; macOS: Keychain → Always Trust). The cert lives in `~/.readback/certs/`, regenerated if your LAN IP changes. Bring your own with `--cert cert.pem --key key.pem`.

---

## Configuration

Edit `config.yaml` (or pass `--config path`):

| Key | What | Default |
|---|---|---|
| `ollama.model` | Ollama model for Summary mode | `nemotron-3-nano:4b` |
| `ollama.host` | Ollama endpoint | `http://localhost:11434` |
| `tts.csm.speaker` | Active voice (`conversational_a`/`_b` or a clone `name`) | `kay` (shipped clone) |
| `tts.csm.precision` | `bf16` (clean+fast) / `fp16` / `fp32` (slowest, cleanest) | `bf16` |
| `tts.csm.temperature` | Delivery: lower = composed, higher = livelier | `0.6` |
| `tts.csm.ref_max_sec` | Cap reference-clip length (s); `null` = full clip | `null` |
| `tts.csm.voices` | Clone voices (`name`, `label`, `wav`, `ref_text`, `speaker`) | (sample `kay`) |
| `tts.csm.lora_path` | LoRA adapter dir from a `csm-mlx finetune` run | `null` |
| `reader.default_mode` | `full` (verbatim) or `summary` (LLM) | `full` |
| `reader.output_dir` | Where generated WAVs are written/served | `~/.readback/reader` |
| `reader.gap_sec` | Silence inserted between synthesized chunks | `0.18` |
| `reader.summary_max_chars` | Cap article text fed to the LLM in Summary mode | `16000` |

CLI overrides: `readback --model qwen3` (per-run model), `--host`, `--port`, `--config`.

---

## How it works

```
URL ─▶ trafilatura fetch + extract (browser-UA fallback) ─▶ clean article text
        │
        ├─ Full mode: read verbatim
        └─ Summary mode: Ollama one-shot → spoken-style explanation
        │
        ▼
   sentence-aware chunking (~280 chars/chunk, paragraph-respecting)
        ▼
   CSM-1B synthesis per chunk (offline) + silence-tidy (cap mid-pauses)
        ▼
   concatenate ─▶ WAV ─▶ served at /audio/<id>.wav
        ▼
   browser: custom player + download (+ transcript in Summary mode)
```

Progress streams over a single WebSocket (`/ws`): `phase` → `progress {done,total}` → `done {title, audio_url, duration_sec, word_count, mode, text?}`. A `cancel` message aborts an in-flight job (stops synthesis mid-stream). CSM runs all model work on a single MLX executor thread (MLX binds its GPU stream to the first thread that touches it), so concurrent read jobs queue naturally.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the system view and [CLAUDE.md](CLAUDE.md) for implementation notes and gotchas.

---

## Changelog

### v0.8.0 — Offline article reader (project pivot + rename to `readback`)
- **Pivoted from a real-time voice assistant to an offline article reader.** Removed the entire live cascade — Parakeet STT, Smart-Turn, webrtcvad, mic capture, echo gate, wake-word, personas, tools, and Obsidian export. The app now does one thing: URL → article → audio. `torch`/`transformers` are gone; TTS is pure MLX (`csm-mlx`), the LLM runs in Ollama.
- **CSM-1B via [csm-mlx](https://github.com/senstella/csm-mlx)** (senstella) replaces the mlx-audio path — cleaner output, bf16, 24 kHz native.
- **Clone-condition voices** (`tts.csm.voices`) — reproduce any voice from a short reference clip; **LoRA fine-tune** pipeline (`finetune/`) for higher-fidelity voices.
- **Reader UI** — custom audio player, Full/Summary toggle, summary transcript with copy, vertically-centered layout, hero-orb synthesis state with Cancel.
- **Renamed `local-tts` → `readback`** (package, CLI, config, runtime dir `~/.readback/`).

---

## License

MIT — see [LICENSE](LICENSE).
