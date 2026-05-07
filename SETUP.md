# Setup Guide

End-to-end setup for `local-tts` on Apple Silicon. Follow once; everything caches afterwards.

## 1. Prerequisites

- macOS on Apple Silicon (M1/M2/M3/M4/M5)
- [Ollama](https://ollama.ai/) installed and running with at least one model pulled
- [uv](https://docs.astral.sh/uv/) installed (`brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- A free [Hugging Face](https://huggingface.co/join) account

## 2. Clone and create the Python environment

```bash
git clone git@github.com:MKS-01/local-tts.git
cd local-tts

uv python install 3.11
uv venv --python 3.11 .venv
source .venv/bin/activate
```

## 3. Vendor Sesame CSM and install dependencies

CSM is not pip-installable, so it's vendored as a sibling repo.

```bash
git clone https://github.com/SesameAILabs/csm vendor/csm
uv pip install -r vendor/csm/requirements.txt
uv pip install -e .
```

## 4. Hugging Face authentication

CSM uses two gated models for tokenization. Both are free, both grant instant access.

### 4a. Request access to the gated models

While logged in to Hugging Face, visit each link, click **"Expand to review and access"**, fill in the short form (Personal use is fine), and submit:

- https://huggingface.co/meta-llama/Llama-3.2-1B
- https://huggingface.co/sesame/csm-1b

Approval is automatic — usually within seconds. Refresh the page; the yellow access banner should disappear.

### 4b. Create an access token

- Go to https://huggingface.co/settings/tokens
- Click **+ Create new token**
- Name: `local-tts`, Type: **Read**
- Click **Create token** and **copy it immediately** (starts with `hf_...`)

### 4c. Log in from the terminal

```bash
huggingface-cli login
# Paste the token when prompted (won't be visible)
# Answer "n" when asked about git credentials
```

Verify:

```bash
python -c "from huggingface_hub import HfApi; print(HfApi().whoami()['name'])"
```

## 5. Download model weights (~6.8GB total)

The `sesame/csm-1b` repo on Hugging Face contains **three redundant copies** of the same model in different formats (`model.safetensors`, `ckpt.pt`, and `transformers-*.safetensors` shards). `local-tts download-models` only fetches the one CSM actually uses (`model.safetensors`), saving ~13GB vs. a naive `snapshot_download`.

### Option A: All-in-one (recommended)

```bash
export HF_HUB_DOWNLOAD_TIMEOUT=120
local-tts download-models
```

This pulls:

| Model | Size | Purpose |
| --- | --- | --- |
| `Whisper base.en` (CTranslate2) | ~150MB | STT |
| `sesame/csm-1b` (`model.safetensors` + voice prompts only) | ~6.3GB | TTS |
| `meta-llama/Llama-3.2-1B` (tokenizer files only) | ~5MB | CSM text tokenizer |
| Mimi audio codec | ~500MB | pulled by CSM on first synthesis |

### Option B: Manual, file-by-file (use if Option A hangs or times out)

`huggingface-cli download` has the strongest resume support if the connection is flaky. Pass `--include` to skip the redundant model copies:

```bash
source /Users/mks/Desktop/C0D3/local-tts/.venv/bin/activate
export HF_HUB_DOWNLOAD_TIMEOUT=120

# 1. Whisper base.en (~150MB)
python -c "from faster_whisper import WhisperModel; WhisperModel('base.en', device='cpu', compute_type='int8')"

# 2. CSM-1B — only the safetensors weights, config, and voice prompts (~6.3GB)
huggingface-cli download sesame/csm-1b \
  --include "model.safetensors" "config.json" "generation_config.json" "prompts/*.wav"

# 3. Llama-3.2-1B — tokenizer only, NOT the 2.5GB weights (~5MB)
huggingface-cli download meta-llama/Llama-3.2-1B \
  --include "tokenizer.json" "tokenizer_config.json" "special_tokens_map.json"

# 4. Mimi audio codec — auto-pulled by CSM on first synthesis; no manual step needed
```

> **Warning** — running `huggingface-cli download sesame/csm-1b` *without* `--include` will pull ~20GB (all three model formats). Always use the `--include` filter above.

Cache lives in `~/.cache/huggingface/hub/`. Partial downloads resume automatically.

## 6. Verify

```bash
# Audio devices
local-tts list-devices

# Ollama models reachable
local-tts list-models

# TTS smoke test (loads CSM, synthesizes one sentence, plays it)
local-tts test-tts "hello from sesame"
```

First TTS call takes 30-60s while MPS compiles kernels. Subsequent synthesis is much faster (~1.5–2.5s per sentence on M-series).

## 7. Run the app

```bash
# Voice mode (default)
local-tts run

# Text mode
local-tts run --text-mode

# Override Ollama model
local-tts run --model llama3.1:8b
```

In-app:
- **F4** — toggle voice ↔ text mode
- **Speak during a response** — interrupt the assistant
- **Ctrl+C** — quit

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `GatedRepoError` on download | You haven't accepted the model's license yet. Visit the model page on huggingface.co and click "Expand to review and access". |
| `ReadTimeout` mid-download | Set `HF_HUB_DOWNLOAD_TIMEOUT=120` (or higher), then re-run. Partial files resume automatically. |
| `NO_TORCH_COMPILE` warnings | Already handled — `local_tts/tts/synthesizer.py` sets it before importing torch. |
| Microphone not detected | Grant microphone permission in System Settings → Privacy & Security → Microphone for your terminal app. |
| `mps not available` on import | Confirm with `python -c "import torch; print(torch.backends.mps.is_available())"`. Should print `True`. If `False`, your PyTorch build wasn't compiled for MPS — reinstall with `uv pip install --force-reinstall torch torchaudio`. |
| Bluetooth audio sounds bad | macOS routes mic-on Bluetooth devices to a low-quality SCO codec. Use wired audio or built-in speakers for best quality. |

## Disk usage

After full setup (with the filtered download in Option A or B):
- `.venv/` — ~2.5GB
- `~/.cache/huggingface/hub/` — ~7GB (CSM `model.safetensors` + voice prompts + Llama tokenizer + Mimi)
- Whisper cache — ~150MB

Total: **~9.5GB**.

If you accidentally pulled the full `sesame/csm-1b` repo (no `--include` filter), `~/.cache/huggingface/hub/` will be ~20GB. To reclaim space, delete the unused blobs:

```bash
# Remove the redundant ckpt.pt and transformers-*.safetensors files
find ~/.cache/huggingface/hub/models--sesame--csm-1b -name "ckpt.pt" -delete
find ~/.cache/huggingface/hub/models--sesame--csm-1b -name "transformers-*" -delete
```
