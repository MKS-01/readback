# Fine-tuning the reading voice (CSM-1B LoRA)

Teach CSM-1B a target voice/tone by **LoRA fine-tuning** with
[`csm-mlx`](https://github.com/senstella/csm-mlx/blob/master/FINETUNING_CLI.md),
then load the small adapter at inference. LoRA (not full fine-tune) is the right
fit for an **M5 Pro / 48 GB**: full fine-tuning needs Mac-Studio-class RAM, while
LoRA trains in well under 48 GB and produces a ~tens-of-MB `adapters.safetensors`
that's trivial to keep, swap, or revert.

> **Data reality:** voice fine-tuning wants **minutes** of clean audio per
> speaker, not seconds. The two seed clips (`casual`, `therapist`) are here only
> to show the format — add more before expecting good results.

## 1. Add audio

One subfolder per **conversation**; one `speakerN` per voice. Each clip needs a
matching `.txt` transcript with the same name. Clips: mono, 24 kHz WAV preferred
(`scripts/make_clone_voice.sh` re-encodes anything). Keep speaker IDs consistent
across folders — here **speaker0 = casual, speaker1 = therapist**.

```
finetune/data/
  casual_01/
    001_speaker0.wav      002_speaker0.wav   …   # sequential turns
    001_speaker0.txt      002_speaker0.txt   …
  casual_02/              …
  therapist_01/
    001_speaker1.wav
    001_speaker1.txt
```

Rules (from `csm-mlx convert`): filename must contain `speaker<digits>`
(case-insensitive); audio without a same-stem `.txt` is skipped; files are
ordered naturally within a folder.

### Transcripts

The reader app dropped ASR, so transcripts are supplied as `.txt`. To auto-draft
them (then **review for accuracy** — a wrong transcript degrades the voice):

```bash
.venv/bin/python -m pip install mlx-whisper      # one-off, not a project dep
.venv/bin/python finetune/transcribe.py          # writes .txt for every clip
```

## 2. Build the dataset JSON

```bash
.venv/bin/csm-mlx finetune convert finetune/data finetune/dataset.json
```

## 3. Train (LoRA)

Tuned for 48 GB — batch 1 + gradient accumulation + checkpointing keeps RAM low
(`csm-mlx` does no compute amortization, so big batches blow up memory):

```bash
.venv/bin/csm-mlx finetune lora sft \
  --data-path finetune/dataset.json \
  --output-dir finetune/runs/v1 \
  --lora-rank 8 --lora-alpha 16 \
  --epochs 10 \
  --batch-size 1 \
  --gradient-accumulation-steps 8 \
  --gradient-ckpt \
  --learning-rate 5e-4
```

Output: `finetune/runs/v1/adapters.safetensors` + `adapter_config.json`. Re-running
with the same `--output-dir` resumes. If RAM still spikes, lower `--lora-rank` to
4; if the voice underfits, raise `--epochs` or add data.

## 4. Use it in the reader

Wired and ready. In `config.yaml`, point at the run dir:

```yaml
tts:
  csm:
    temperature: 0.8          # FINETUNING preset
    lora_path: "finetune/runs/v1"
```

`CsmEngine._load_impl` then calls `csm_mlx.load_adapters` over the base weights,
and generation switches to **empty context** (the voice lives in the adapter, not
a reference clip — per FINETUNING). Restart the server to load it. The fine-tuned
speakers are selected by the existing voice picker → speaker id (0, 1, …); set the
training `speakerN` ids to the voices you want behind those slots.

> Quick check before going through the UI:
> ```bash
> .venv/bin/python -c "from local_tts.config import Config; from local_tts.tts.synthesizer import Synthesizer; import soundfile as sf, numpy as np; \
> c=Config.load(); s=Synthesizer(c.tts); s.load(); \
> sf.write('/tmp/ft.wav', np.asarray(s.synthesize('This is the fine-tuned reading voice.'),dtype=np.float32), s.sample_rate); print('wrote /tmp/ft.wav')"
> ```
