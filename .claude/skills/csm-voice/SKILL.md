---
name: csm-voice
description: Change, clone, tune, or fine-tune the reader's CSM-1B TTS voice. Use when the user wants the spoken output to sound like a specific person/character (e.g. "match this voice", "make it a young female professor", "use this clip"), to add a custom voice, tune delivery/tone, or fine-tune. Covers the clone-condition path (a reference clip), delivery tuning (temperature), and the LoRA fine-tune pipeline.
---

# Tuning the CSM-1B reading voice

The reader's TTS is **CSM-1B via csm-mlx** (`readback/tts/csm_engine.py`). Use this
skill whenever the user wants to change *who* the reader sounds like.

## Mental model (state this honestly to the user)

- **Timbre, gender, apparent age, accent = the reference clip** (clone) or the
  **LoRA training audio** (fine-tune). There is **no parameter** for age /
  gender / "attractiveness" — CSM reproduces whatever voice it is given. If the
  target isn't matched, the fix is a **better clip**, not settings.
- **`temperature` only changes delivery** (steadiness vs. variation), not who it
  sounds like. ~0.6 = composed/measured; ~0.8 = livelier. **Below ~0.55 with a
  short (<5 s) reference the clone destabilizes** (rambles/repeats, runs way over
  expected length — a tell that it went unstable).
- A clean **5–8 s** reference conditions far more reliably than a ~4 s one.
- Clone-condition beats LoRA for a **single short clip**; LoRA needs **minutes**
  of the target speaker and is worth it only with that much data.

## A. Clone-condition a voice from a clip (default path)

1. Put the clip in `voice/` as mono 24 kHz 16-bit wav — re-encode anything with
   `ffmpeg -i <in> -ac 1 -ar 24000 -sample_fmt s16 voice/<name>.wav`
   (renaming an .m4a to .wav does NOT work; the bytes stay AAC).
   `voice/*.wav` is gitignored.
2. Get the **exact transcript** (CSM conditions on the audio+text pair; a
   mismatch garbles the voice). ASR was removed from the app, so transcribe
   one-off with mlx-whisper, then **uninstall it** (not a project dep):
   ```bash
   .venv/bin/python -m pip install -q mlx-whisper
   .venv/bin/python -c "import mlx_whisper; print(mlx_whisper.transcribe('voice/CLIP.wav', path_or_hf_repo='mlx-community/whisper-small-mlx')['text'].strip())"
   .venv/bin/python -m pip uninstall -y mlx-whisper -q
   ```
3. Register it in `config.yaml` under `tts.csm.voices` and set it as the default
   `speaker`:
   ```yaml
   tts:
     csm:
       speaker: "kay"          # the voice's `name`
       temperature: 0.6
       voices:
         - name: "kay"
           label: "Kay ★"
           wav: "voice/voice_kay_long.wav"   # relative to config.yaml
           speaker: 0
           ref_text: "Exact transcript of the clip — MUST match the audio."
   ```
   This is plumbed end-to-end: `CsmVoicePrompt` (`config.py`) →
   `voices_for` / `_config_voice` / `_ref_for` (`csm_engine.py`) →
   `voices_for(cfg.tts.csm)` in `server.py` (dynamic picker). Restart the server.

4. **Always generate a sample and let the user judge the match** before declaring
   done (you can't hear timbre/age). One-off, conditions on the clip directly:
   ```python
   import numpy as np, soundfile as sf, mlx.core as mx
   from csm_mlx import CSM, csm_1b, generate, Segment
   from csm_mlx.utils import read_audio
   from mlx_lm.sample_utils import make_sampler
   from huggingface_hub import hf_hub_download
   csm = CSM(csm_1b()); csm.load_weights(hf_hub_download("senstella/csm-1b-mlx","ckpt.safetensors"))
   csm.set_dtype(mx.bfloat16); mx.eval(csm.parameters())
   ref = Segment(speaker=0, text="<exact transcript>", audio=read_audio("voice/CLIP.wav", 24000))
   a = generate(csm, text="Some article-style sentence to read.", speaker=0,
                context=[ref], max_audio_length_ms=15000, sampler=make_sampler(temp=0.6, top_k=50))
   sf.write("/Users/mks/Downloads/voicetest.wav", np.asarray(a,dtype=np.float32), 24000)
   ```
   Or, once registered, go through the real path: `Synthesizer(cfg.tts).synthesize(...)`.

## B. Tune delivery

Generate the same text at a few temperatures (0.6 / 0.8) so the user picks
cadence; skip 0.5 on short refs (unstable). It's a one-line `config.yaml` change.

## C. LoRA fine-tune (more audio, higher fidelity)

Scaffolded in `finetune/` (see `finetune/README.md`). Flow:
`finetune/transcribe.py` → `csm-mlx finetune convert finetune/data finetune/dataset.json`
→ `csm-mlx finetune lora sft … -o finetune/runs/v1` (M5-tuned: `--batch-size 1
--gradient-accumulation-steps 8 --gradient-ckpt`). Then set
`tts.csm.lora_path: "finetune/runs/v1"` + `temperature: 0.8`. The engine loads the
adapter (`load_adapters`) and generates with **empty context** (the voice lives in
the adapter — `_ref_for` returns `[]` when `lora_path` is set).

## Gotchas

- Reference `ref_text` must match the clip exactly. Verify the auto-transcript.
- Custom-voice `wav` paths resolve relative to `config.yaml` (`Config.load`).
- Server must be restarted to pick up `config.yaml` changes.
- Clean up: uninstall mlx-whisper after transcribing; it is not in `pyproject.toml`.
