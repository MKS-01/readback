# Setup Guide

End-to-end setup for `readback` on Apple Silicon. Follow once; model weights cache
afterwards.

## Fastest path — one command

First-time on a Mac (Apple Silicon)? The setup script does everything below for
you — prerequisite checks, venv + install, CLI + dashboard build, and optional
model/weight downloads. Safe to re-run.

```bash
git clone git@github.com:MKS-01/readback.git && cd readback
bash scripts/setup.sh
```

The rest of this guide is the manual, step-by-step version (and the reference for
flags, verification, and troubleshooting).

## 1. Prerequisites

- macOS on Apple Silicon (M1–M5).
- Python 3.10–3.12 (3.12 recommended).
- [Bun](https://bun.sh) 1.0+ (to build/run the terminal CLI).

No Hugging Face login is required — CSM weights come from the ungated
`senstella/csm-1b-mlx` re-host, and MLX-LM models from `mlx-community`.

## 2. Clone and install

```bash
git clone git@github.com:MKS-01/readback.git
cd readback

python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .          # csm-mlx + mlx-lm + mlx-vlm pulled automatically
```

## 3. Install the CLI (one-time)

```bash
cd src/cli && ./install.sh && cd ../..   # → ~/.local/bin/readback-cli
```

Or run it from source without installing: `cd src/cli && bun run start`.
Re-run `./install.sh` after pulling changes (the standalone binary is compiled).

## 4. Run

```bash
readback-cli             # auto-spawns the Python server if none is running
# or start the server alone:
readback                 # http://127.0.0.1:8000 (WS/API backend only, no UI)
```

On the **first read**, CSM-1B downloads (~6 GB) from Hugging Face and the MLX graph
warms up — the first synthesis takes noticeably longer; subsequent runs are fast.
Weights cache in `~/.cache/huggingface/hub/`.

Useful flags:

```bash
readback --model mlx-community/Qwen3.5-4B-4bit  # override the LLM for this run
readback --port 9000                   # different port
readback --config /path/to/config.yaml # custom config
readback-cli --host 192.168.1.x --port 8000 --no-spawn   # CLI → remote server
```

## 5. Verify

1. Run `readback-cli` — the home screen renders; with no server running it
   spawns one (first boot waits on model load).
2. Paste an article URL in **Full** mode — phases stream (*fetching →
   synthesizing N/M*), then the player appears and audio plays via `afplay`.
3. Switch to **Summary** (`/mode`) and read again —
   `t` toggles the word-synced transcript.
4. `q` exits; a server the CLI spawned dies with it.

Voice-only smoke test from a REPL:

```bash
.venv/bin/python -c "from readback.config import Config; from readback.tts.synthesizer import Synthesizer; \
import soundfile as sf, numpy as np; c=Config.load(); s=Synthesizer(c.tts); s.load(); \
sf.write('/tmp/test.wav', np.asarray(s.synthesize('Hello from readback.'),dtype=np.float32), s.sample_rate); print('wrote /tmp/test.wav')"
```

## Tests

A `pytest` suite covers the pure logic — chunking, silence-tidy, TTS text scrub,
the SQLite library, and the `<think>` stripper. It needs no MLX/CSM or GPU, so it
runs anywhere (and in CI on Linux):

```bash
pip install -e '.[test]'   # or: pip install -r requirements-pi.txt pytest
pytest                     # config (testpaths, src on path) is in pyproject.toml
```

CI (`.github/workflows/ci.yml`) runs the same suite on Python 3.10–3.12 on every
push and PR, installing the `requirements-pi.txt` subset + pytest.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Summary mode errors / "error running the LLM" | The MLX model isn't downloaded. Run `python -c "from huggingface_hub import snapshot_download; snapshot_download('mlx-community/Qwen3.5-9B-4bit')"` or use a model you've already downloaded. Check `llm.model` in `config.yaml`. |
| First synthesis hangs for a while | One-time ~6 GB CSM download + MLX graph warm-up. Subsequent synth is fast. |
| `ReadTimeout` mid-download | `export HF_HUB_DOWNLOAD_TIMEOUT=120` and re-run; partial files resume. |
| CLI can't find/spawn the server | Spawn prefers `.venv/bin/readback` at the repo root — make sure `pip install -e .` ran in `.venv`, or start `readback` yourself and use `--no-spawn`. |
| "no readable article text found" | The page isn't a standard article (paywall, JS-rendered, or login wall). Try a different URL. |
| Voice sounds garbled on a clone | `ref_text` must exactly match the clip; use a clean 5–8 s reference; raise `tts.csm.temperature` toward 0.6–0.8. See `.claude/skills/csm-voice`. |

## Disk usage

- `.venv/` — ~2–3 GB.
- `~/.cache/huggingface/hub/` — ~6.5 GB (CSM weights) + ~4.5 GB per MLX-LM model
  (summary) + ~2 GB vision model (OCR).
- Generated audio + the library DB — a `readback-audio-db/` folder beside the
  repo (`reader.output_dir` / `reader.library_db`; grows with use). Deleting a
  read from the dashboard removes its WAV; clearing the folder wipes the library.
