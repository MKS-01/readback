# Setup Guide

End-to-end setup for `readback` on Apple Silicon. Follow once; model weights cache
afterwards.

## 1. Prerequisites

- macOS on Apple Silicon (M1–M5).
- Python 3.10–3.12 (3.11 recommended).
- [Ollama](https://ollama.ai/) — only needed for **Summary** mode. Install it and
  pull a chat model:
  ```bash
  ollama serve &                     # or launch the desktop app
  ollama pull nemotron-3-nano:4b     # default; any chat model works
  ```
- [Node.js](https://nodejs.org/) 18+ (to build the React frontend).

No Hugging Face login is required — the CSM weights come from the ungated
`senstella/csm-1b-mlx` re-host.

## 2. Clone and install

```bash
git clone git@github.com:MKS-01/readback.git
cd readback

python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .          # csm-mlx is a git dependency, pulled automatically
```

## 3. Build the frontend (one-time)

```bash
cd readback/web/frontend
npm install
npm run build            # writes ../static/dist
cd ../../..
```

Re-run `npm run build` after editing anything under `readback/web/frontend/src/`.
The server serves this build directly — if you skip the build, the page won't load.

## 4. Run

```bash
readback                 # http://127.0.0.1:8000
# or, without installing the console script:
python -m readback
```

On the **first read**, CSM-1B downloads (~6 GB) from Hugging Face and the MLX graph
warms up — the first synthesis takes noticeably longer; subsequent runs are fast.
Weights cache in `~/.cache/huggingface/hub/`.

Useful flags:

```bash
readback --model qwen3                 # override the Ollama model for this run
readback --port 9000                   # different port
readback --config /path/to/config.yaml # custom config
readback --host 0.0.0.0 --auto-cert    # LAN access over HTTPS (phone/tablet)
```

## 5. Verify

1. Open `http://127.0.0.1:8000` — the orb breathes, the URL field is ready.
2. Paste an article URL, leave it on **Full article**, hit **→**.
3. The orb takes over with *Fetching… → Synthesizing N/M*, then a player appears,
   audio plays, and **↓ Download audio** works.
4. Switch to **Summary** (requires Ollama running) and read again — after
   synthesis, **Show transcript** reveals the spoken summary.

Voice-only smoke test from a REPL:

```bash
.venv/bin/python -c "from readback.config import Config; from readback.tts.synthesizer import Synthesizer; \
import soundfile as sf, numpy as np; c=Config.load(); s=Synthesizer(c.tts); s.load(); \
sf.write('/tmp/test.wav', np.asarray(s.synthesize('Hello from readback.'),dtype=np.float32), s.sample_rate); print('wrote /tmp/test.wav')"
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Summary mode errors / "error talking to Ollama" | Ollama isn't running or the model isn't pulled. `ollama serve` + `ollama pull <model>`; check `ollama.host` in `config.yaml`. |
| First synthesis hangs for a while | One-time ~6 GB CSM download + MLX graph warm-up. Subsequent synth is fast. |
| `ReadTimeout` mid-download | `export HF_HUB_DOWNLOAD_TIMEOUT=120` and re-run; partial files resume. |
| Page looks unstyled / old | You didn't build the frontend, or built it stale. Re-run `npm run build`. |
| "no readable article text found" | The page isn't a standard article (paywall, JS-rendered, or login wall). Try a different URL. |
| Voice sounds garbled on a clone | `ref_text` must exactly match the clip; use a clean 5–8 s reference; raise `tts.csm.temperature` toward 0.6–0.8. See `.claude/skills/csm-voice`. |

## Disk usage

- `.venv/` — ~2–3 GB.
- `~/.cache/huggingface/hub/` — ~6.5 GB (CSM `ckpt.safetensors` + Mimi codec +
  Sesame voice prompts).
- Generated audio — `~/.readback/reader/` (grows with use; safe to clear).
