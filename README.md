<h1 align="center">📖 readback</h1>

<p align="center">
  <strong>Turn any article into a podcast — entirely on your Mac.</strong><br>
  Paste a URL. Get a clean, natural-voice reading of the whole piece.<br>
  No cloud. No API keys. Nothing leaves your machine.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Runs-100%25_offline-6366f1?style=for-the-badge&logo=ghostery&logoColor=white" alt="Runs 100% offline">
  <img src="https://img.shields.io/badge/Apple_Silicon-MLX_·_Metal-black?style=for-the-badge&logo=apple&logoColor=white" alt="Apple Silicon">
  <img src="https://img.shields.io/badge/Voice-CSM--1B-ec4899?style=for-the-badge&logo=soundcharts&logoColor=white" alt="CSM-1B neural TTS">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/React_18-Vite-61DAFB?style=flat-square&logo=react&logoColor=white" alt="React 18">
  <img src="https://img.shields.io/badge/FastAPI-WebSocket-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="MIT License">
</p>

<p align="center">
  <img src="media/screenshot-one.png" alt="readback — the custom audio player and orbital synthesis state" width="820">
</p>

<p align="center">
  <strong>🔊 <a href="media/sample-read.wav">Hear a sample read</a></strong><br>
  <sub>Sample voice: <strong>kay</strong> — a custom-tuned clone voice on CSM-1B</sub>
</p>

---

## What it does

1. **Paste a URL.** readback extracts the clean article text — no nav, ads, or boilerplate.
2. **Pick a mode.** *Full* reads it verbatim; *Summary* has a local LLM turn it into a tight spoken explanation first.
3. **Listen.** It's synthesized offline with **CSM-1B** and played in a minimalist browser player — or downloaded as a WAV.

Because there's no live conversation to keep up with, readback synthesizes the
**whole piece up front**, then hands back one gapless audio file — so voice
quality wins over latency.

---

## Quick start

You need **macOS on Apple Silicon**, **Python 3.10–3.12**, **Node 18+**, and
[Ollama](https://ollama.ai/) (only for Summary mode).

```bash
# 1. Ollama for Summary mode (skip if you only want Full mode)
ollama serve &                          # or launch the desktop app
ollama pull gemma4:26b                  # default; any chat model works

# 2. Install
git clone git@github.com:MKS-01/readback.git && cd readback
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .                        # csm-mlx is a git dep, pulled automatically

# 3. Build the web UI (one-time; rerun after editing readback/web/frontend/)
cd readback/web/frontend && npm install && npm run build && cd ../../..

# 4. Run
readback                                # http://127.0.0.1:8000
```

On the **first read**, the CSM-1B weights (~6 GB) download from Hugging Face (no
login) and the MLX graph warms up — so the first synthesis is slow; later runs
are fast. See [SETUP.md](SETUP.md) for verification, flags, and troubleshooting.

---

## How it works

```
URL ─▶ fetch + extract ──▶ [Summary: local LLM] ──▶ chunk ──▶ TTS ──▶ WAV ─▶ browser
       (trafilatura)          (Ollama)                       (CSM-1B, offline)
```

1. **Extract** — `trafilatura` pulls the article body (browser-UA fallback for sites that 403), then light scrubbing removes URLs and citation markers so they aren't read aloud.
2. **Summarize** (Summary mode only) — one Ollama call rewrites the article as a spoken explanation.
3. **Chunk + synthesize** — the text is split into sentence-aware chunks, each synthesized with CSM-1B, silence-trimmed, and joined with small gaps.
4. **Serve** — the finished WAV is served over HTTP; progress streams live over a WebSocket.

A single FastAPI process drives it all. CSM runs on one MLX/Metal thread (MLX
binds its GPU stream to the first thread that touches it), so read jobs queue
naturally. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system view.

---

## Tech stack

| Layer | Technology |
|---|---|
| **Extraction** | [trafilatura](https://trafilatura.readthedocs.io/) — URL → clean text (+ browser-UA fallback) |
| **Summary (optional)** | [Ollama](https://ollama.ai/) — default `gemma4:26b`; any pulled chat model works |
| **TTS** | [CSM-1B](https://huggingface.co/senstella/csm-1b-mlx) (Sesame) via [csm-mlx](https://github.com/senstella/csm-mlx) — MLX/Metal, 24 kHz, fp32 |
| **Voices** | 2 built-in reading voices + **clone any voice from a short clip** + optional **LoRA fine-tuning** |
| **Server** | [FastAPI](https://fastapi.tiangolo.com/) + WebSocket — streams progress, serves the WAV |
| **Frontend** | React 18 + TypeScript + Vite + zustand — three.js orb, custom audio player, dark "Ghost" theme |

---

## Voices

readback's voice comes from a short **reference clip** that CSM conditions on —
the clip's timbre, age, and accent are what you hear.

- **Built-in** — `conversational_a` (female ★) / `conversational_b` (male), an even literary reading tone. English-best.
- **Clone** — drop a clean 5–8 s mono clip into `voice/` and register it under `tts.csm.voices` (the bundled config ships a sample `kay` voice):

  ```yaml
  tts:
    csm:
      speaker: "kay"          # default voice = the name below
      temperature: 0.6        # delivery: lower = composed, higher = livelier
      voices:
        - name: "kay"
          label: "Kay ★"
          wav: "voice/k.wav"                          # relative to config.yaml
          speaker: 0
          ref_text: "Exact transcript of the clip."   # MUST match the audio
  ```

  `ref_text` **must** be the clip's exact transcript — a mismatched pair garbles
  the voice. `temperature` tunes *delivery*, not *who* it sounds like.

- **Fine-tune** (optional) — for higher fidelity with more audio there's a LoRA pipeline in [`finetune/`](finetune/README.md); point `tts.csm.lora_path` at the trained adapter.

Full clone/tune procedure: `.claude/skills/csm-voice`.

---

## Configuration

Edit `config.yaml` (or pass `--config path`). The defaults work out of the box.

| Key | What | Default |
|---|---|---|
| `ollama.model` | Ollama model for Summary mode | `gemma4:26b` |
| `ollama.host` | Ollama endpoint | `http://localhost:11434` |
| `tts.csm.speaker` | Active voice (`conversational_a`/`_b` or a clone `name`) | `kay` |
| `tts.csm.precision` | `bf16` (clean+fast) / `fp16` / `fp32` (slowest, cleanest) | `fp32` |
| `tts.csm.temperature` | Delivery: lower = composed, higher = livelier | `0.6` |
| `tts.csm.voices` | Clone voices (`name`, `label`, `wav`, `ref_text`, `speaker`) | sample `kay` |
| `tts.csm.lora_path` | LoRA adapter dir from a `csm-mlx finetune` run | `null` |
| `reader.default_mode` | `full` (verbatim) or `summary` (LLM) | `full` |
| `reader.output_dir` | Where generated WAVs are written/served | `~/.readback/reader` |
| `reader.gap_sec` | Silence inserted between synthesized chunks | `0.18` |
| `reader.summary_max_chars` | Cap article text fed to the LLM in Summary mode | `16000` |

CLI overrides: `readback --model gemma4:e4b`, `--host`, `--port`, `--config`.

**LAN access (phone/tablet):** `readback --host 0.0.0.0 --auto-cert` serves over
HTTPS; the startup banner prints the network URL, cert fingerprint, and a
`/cert.pem` link to trust once per device.

---

## License

MIT — see [LICENSE](LICENSE).
