# Setup Guide

End-to-end setup for `vox-tinker` on Apple Silicon. Follow once; model weights cache afterwards. For a quick overview see the [README](README.md); this guide adds the details and troubleshooting.

## 1. Prerequisites

- macOS on Apple Silicon (M1/M2/M3/M4/M5) — MLX/Metal is required for Parakeet ASR and Qwen3-TTS.
- [Ollama](https://ollama.ai/) installed and running, with at least one chat model pulled.
- Python 3.11 (3.10+ works; 3.11 recommended).
- [Node.js](https://nodejs.org/) 18+ (only to build the web UI once).

No Hugging Face account or login is needed — Parakeet, Qwen3-TTS, and Smart-Turn are public and download automatically on first use.

## 2. Pull an Ollama model

```bash
ollama serve &                          # or launch the Ollama desktop app
ollama pull nemotron-3-nano:4b          # default; any pulled chat model is selectable
```

Tool/function-calling (`tools.enabled: true`, the default) needs a tool-capable model — `nemotron-3-nano:4b` qualifies.

## 3. Clone and create the Python environment

```bash
git clone git@github.com:MKS-01/vox-tinker.git
cd vox-tinker

python3.11 -m venv .venv && source .venv/bin/activate
pip install torch==2.4.0 torchaudio==2.4.0   # pinned; transformers<5 needs torch 2.4
pip install -e .
pip install -e ".[wakeword]"                 # optional; only to re-enable the hidden wake-word UI
```

> **Why the torch pin.** `transformers` is held `<5` (Smart-Turn's `WhisperFeatureExtractor` and Qwen3-TTS run fine on 4.x). transformers 5.x's import chain needs torch ≥ 2.5, so torch is pinned to 2.4. mlx-audio *declares* `transformers>=5.5`; if pip's resolver objects, install with `pip install -e . --no-deps` (all other deps are already satisfied by the step above).

## 4. Build the web UI

```bash
cd vox_tinker/web/frontend && npm install && npm run build && cd ../../..
```

This writes the Vite bundle to `vox_tinker/web/static/dist/`. Rerun after any frontend edit. (A legacy vanilla-JS bundle is served if `dist/` is missing, so this step can be skipped for a first smoke test.)

## 5. First run

```bash
vox-tinker                              # http://127.0.0.1:8000
```

On first launch the speech models download silently (no HF login):

| Model | Size | Purpose |
| --- | --- | --- |
| Parakeet `parakeet-tdt-0.6b-v2` (MLX) | ~2.5 GB | STT (default, streaming) |
| Qwen3-TTS-0.6B (mlx-audio) | ~0.6 GB | TTS, 24 kHz |
| Smart-Turn v3 (ONNX) | ~8 MB | semantic end-of-turn |
| faster-whisper checkpoint | ~75 MB–3 GB | only if you switch ASR engine to Whisper |

Then open the page → say "hello" → a live partial caption appears → the reply streams and speaks. The first Parakeet/Qwen utterance is slow (~2–3 s) for one-time MLX graph warm-up; warm calls are near-real-time.

## 6. Run options

```bash
vox-tinker                                      # localhost only (HTTP)
vox-tinker --model nemotron3:33b                # override ollama.model for this run
vox-tinker --config /path/to/config.yaml        # custom config file
vox-tinker --host 0.0.0.0 --auto-cert           # LAN-reachable over HTTPS (phone/tablet)
vox-tinker --host 0.0.0.0 --cert c.pem --key k.pem   # bring your own cert
```

Browsers block the mic on plain HTTP for non-localhost origins, so use `--auto-cert` for LAN access — the startup banner prints the URL, the cert's SHA-256 fingerprint, and a `/cert.pem` download link to trust on each device. See the README's "Cross-device access" section for the per-OS trust steps.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `pip install -e .` fails on a transformers/mlx-audio conflict | Run `pip install -e . --no-deps` (the torch/transformers pins from step 3 are already installed). |
| `No module named 'mlx'` / MLX errors | You're not on Apple Silicon, or torch wasn't installed first. Confirm `python -c "import mlx.core"` works. |
| Ollama connection refused | Start it: `ollama serve` (or the desktop app), and pull a model (`ollama pull nemotron-3-nano:4b`). |
| Empty model picker in Settings | No models pulled in Ollama yet — `ollama list` should show at least one. |
| Mic not detected / no captions | Grant mic permission in System Settings → Privacy & Security → Microphone for your browser. |
| First reply takes ~2–3 s | One-time MLX graph warm-up for Parakeet/Qwen; subsequent calls are fast. |
| Bluetooth audio sounds bad | macOS routes mic-on Bluetooth devices to a low-quality SCO codec. Use wired audio or built-in speakers. |
| Page shows the old/plain UI | You haven't run `npm run build` (step 4) — the server is falling back to the legacy bundle. |

## Disk usage

After setup:
- `.venv/` — ~2–3 GB
- `~/.cache/huggingface/hub/` — ~3 GB (Parakeet + Qwen3-TTS + Smart-Turn; + Whisper only if used)
- Ollama models — separate, under `~/.ollama/` (e.g. `nemotron-3-nano:4b` ≈ 2.5 GB)

Auto-generated TLS certs (with `--auto-cert`) live in `~/.vox-tinker/certs/`; crash-recovery session JSONLs in `~/.vox-tinker/sessions/`.
