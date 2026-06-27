# Fine-tuning the reading voice (CSM-1B LoRA)

Teach CSM-1B a target voice by **LoRA fine-tuning** with
[`csm-mlx`](https://github.com/senstella/csm-mlx/blob/master/FINETUNING_CLI.md).
LoRA produces a small adapter (~tens of MB) that's trivial to keep, swap, or
revert — full fine-tuning needs Mac-Studio-class RAM, while LoRA trains
comfortably under 48 GB.

## Why LoRA over clone-conditioning?

Clone-conditioning (the `voices:` config) mimics a voice from a short reference
clip. It works for demos, but across a long article the voice **drifts** — CSM
re-conditions every chunk, and small variations compound. LoRA embeds the voice
into the model weights themselves:

| | Clone-condition | LoRA fine-tune |
|---|---|---|
| **Data needed** | One 5–12 s clip | 3–5 min of clean audio |
| **Voice stability** | Drifts across chunks | Consistent — voice is in the weights |
| **Inference speed** | Slower (reference prefill per chunk) | Faster (empty context, no prefill) |
| **Quality ceiling** | Limited by clip length + temperature | Higher — learns prosody, not just timbre |
| **Setup time** | Instant (edit config.yaml) | ~30 min training on M5/48 GB |

## Quick start

```bash
# 0. Prep audio: mono 24 kHz WAV clips (5–15 s each), 3–5 min total
#    Put them in src/finetune/data/<conversation_name>/
#    Filename must contain speaker<N> (e.g. 001_speaker0.wav)
mkdir -p src/finetune/data/reading_01

# 1. Auto-transcribe (install mlx-whisper first, one-off)
.venv/bin/python -m pip install mlx-whisper
.venv/bin/python src/finetune/transcribe.py
# ⚠ REVIEW the .txt files — wrong transcripts degrade the voice

# 2. Build dataset
.venv/bin/csm-mlx finetune convert src/finetune/data src/finetune/dataset.json

# 3. Train (~20–30 min on M5/48 GB)
.venv/bin/csm-mlx finetune lora sft \
  --data-path src/finetune/dataset.json \
  --output-dir src/finetune/runs/v1 \
  --lora-rank 8 --lora-alpha 16 \
  --epochs 10 \
  --batch-size 1 \
  --gradient-accumulation-steps 8 \
  --gradient-ckpt \
  --learning-rate 5e-4

# 4. Use it
#    In config.yaml:
#      tts:
#        csm:
#          lora_path: "src/finetune/runs/v1"
#          temperature: 0.8
#    Then restart the server.

# 5. Quick test (no server needed)
.venv/bin/python -c "
from readback.config import Config
from readback.tts.synthesizer import Synthesizer
import soundfile as sf
c = Config.load(); s = Synthesizer(c.tts); s.load()
audio = s.synthesize('This is the fine-tuned reading voice.')
sf.write('/tmp/ft-test.wav', audio, s.sample_rate)
print('wrote /tmp/ft-test.wav')
"
```

## Detailed steps

### 1. Add audio

One subfolder per **conversation**; one `speakerN` per voice. Each clip needs a
matching `.txt` transcript with the same stem. Clips should be mono, 24 kHz WAV
(re-encode anything: `ffmpeg -i <in> -ac 1 -ar 24000 -sample_fmt s16 <out>.wav`).

```
src/finetune/data/
  reading_01/
    001_speaker0.wav      002_speaker0.wav   …
    001_speaker0.txt      002_speaker0.txt   …
  reading_02/             …
```

Rules (from `csm-mlx convert`): filename must contain `speaker<digits>`
(case-insensitive); audio without a same-stem `.txt` is skipped; files are
ordered naturally within a folder.

### 2. Transcribe

```bash
.venv/bin/python -m pip install mlx-whisper      # one-off, not a project dep
.venv/bin/python src/finetune/transcribe.py      # writes .txt for every clip
```

CSM conditions on the (audio, text) pair, so transcripts **must be accurate**.
Always review the generated `.txt` files and fix mistakes before training.

### 3. Build the dataset JSON

```bash
.venv/bin/csm-mlx finetune convert src/finetune/data src/finetune/dataset.json
```

### 4. Train (LoRA)

Tuned for 48 GB — batch 1 + gradient accumulation + checkpointing keeps RAM low:

```bash
.venv/bin/csm-mlx finetune lora sft \
  --data-path src/finetune/dataset.json \
  --output-dir src/finetune/runs/v1 \
  --lora-rank 8 --lora-alpha 16 \
  --epochs 10 \
  --batch-size 1 \
  --gradient-accumulation-steps 8 \
  --gradient-ckpt \
  --learning-rate 5e-4
```

Output: `src/finetune/runs/v1/adapters.safetensors` + `adapter_config.json`.

**Tuning knobs:**
- RAM too high → lower `--lora-rank` to 4
- Voice underfits → raise `--epochs` or add more data
- Re-running with the same `--output-dir` resumes from the last checkpoint

### 5. Use it in readback

In `config.yaml`:

```yaml
tts:
  csm:
    temperature: 0.8          # slightly higher for LoRA (FINETUNING preset)
    lora_path: "src/finetune/runs/v1"
```

`CsmEngine._load_impl` calls `csm_mlx.load_adapters` over the base weights.
Generation switches to **empty context** — the voice lives in the adapter, not a
reference clip, so there's no prefill cost per chunk.

Restart the server to load the adapter. The fine-tuned speakers use the existing
voice picker → speaker id mapping (0, 1, …); set the training `speakerN` ids to
match the voices you want behind those slots.

### Reverting

Remove or comment out `lora_path` in `config.yaml` and restart. The base model
+ clone-condition voices work exactly as before.

## File layout

```
src/finetune/
├── README.md           # this file
├── transcribe.py       # mlx-whisper auto-transcription helper
├── data/               # training clips (gitignored; .gitkeep tracks the dir)
│   └── .gitkeep
├── dataset.json        # generated by csm-mlx convert (gitignored)
└── runs/               # training output (gitignored)
    └── v1/
        ├── adapters.safetensors
        └── adapter_config.json
```
