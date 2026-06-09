# Plans

Planning history for readback — newest entry on top, older entries kept below for
tracking. Each entry carries a date and a status (`proposed` / `in progress` /
`done` / `superseded`).

---

## 2026-06-10 — Tune CSM-1B by config (simple path; no model swap)

**Status: done (Step 1; Steps 2–3 deferred)** — applied 2026-06-10:
`precision: fp32`; kay ref upgraded to an 11 s CSM-bootstrapped clip
(`voice/voice_kay_long.wav`, transcript whisper-verified); summary LLM switched
to `gemma4:26b` (cleaner, structured spoken summaries; nemotron-3-nano was the
fallback). End-to-end sample verified: steady pacing, no instability; only
residual nit is occasional proper-noun articulation ("Fable" ≈ "Table"), which
is LoRA territory. **Step 2 (LoRA) deferred** — revisit only if articulation
bothers in real use; anything more now is overengineering.

### Context

Stay on CSM-1B (user decision — engine swap too expensive; Qwen-TTS/Kokoro
already tried and unwanted). csm-mlx runs the **same weights** as the official
`SesameAILabs/csm`, and every lever that matters is **already plumbed into
`config.yaml`** — so the plan is staged: config-only first, LoRA fine-tune only
if that's not enough. **No app-code changes anywhere.**

Why this works: the open 1B is a *base* model; Sesame's own demo voices
(Maya/Miles) are fine-tuned variants conditioned on good reference audio.
Better reference + right precision/temperature is the official recipe's first
half; the LoRA is the second.

### Step 1 — Config-only tuning (~1 hour, no code)

1. **Better reference clip — the biggest lever.** Current kay ref is one short
   ~4–5 s clip; a clean **8–10 s** clip conditions far more reliably (per
   `.claude/skills/csm-voice`). More kay-source audio if available, else any
   clean recording of a voice you like:
   `scripts/make_clone_voice.sh <in> voice/kay2.wav` → exact transcript via
   one-off mlx-whisper (install → transcribe → uninstall, the skill's pattern)
   → update `wav:` + `ref_text:` under `tts.csm.voices`.
2. **`precision: "fp32"`** — max quality; RTF ~1.4 is fine for an offline reader.
3. **Temperature**: render the same paragraph at 0.6 and 0.7, keep the one that
   sounds better (0.6 measured, 0.7 livelier). Two runs, not a grid.
4. Restart the server, read one real article end-to-end, judge by ear.

### Step 2 — LoRA fine-tune (only if Step 1 isn't enough; the real jump)

Follow `finetune/README.md` **verbatim** — commands already M5/48 GB-tuned:
1. Data: one **LibriVox narrator** (clean public-domain read-speech), 30–60 min
   of chapters → split to 5–15 s clips (ffmpeg) → `finetune/data/` layout.
2. `finetune/transcribe.py` (one-off mlx-whisper) → review transcripts.
3. `csm-mlx finetune convert finetune/data finetune/dataset.json`
4. `csm-mlx finetune lora sft --data-path finetune/dataset.json
   --output-dir finetune/runs/v1 --lora-rank 8 --lora-alpha 16 --epochs 10
   --batch-size 1 --gradient-accumulation-steps 8 --gradient-ckpt
   --learning-rate 5e-4`
5. Result is again just config: `lora_path: "finetune/runs/v1"` +
   `temperature: 0.8`. Quick-check synth (README one-liner), then the server.

### Step 3 — Optional, later (on request only)

YouTube voice extraction for a specific person's voice (yt-dlp + diarization +
review pass). Skipped for now — LibriVox covers the quality goal without the
extra deps and script.

### Deliberately cut for simplicity

Multi-clip conditioning (code change), WER bench script, chunk-size and sampler
experiments, mlx upgrade. Revisit only if Step 2 still disappoints.

### Files touched

- Step 1: `config.yaml`, `voice/*.wav` — nothing else.
- Step 2: `finetune/data/*` + `finetune/runs/v1` + two `config.yaml` lines.

### Verification

- Same test paragraph synthesized before/after each change; pick by ear.
  (Optional: one one-off mlx-whisper transcription to count word errors.)
- Server smoke after each config edit (restart required): paste an article URL
  → Full mode → play + download work; cancel still works (no code touched).

### Honest expectations

Step 1 tightens voice consistency and clarity; Step 2 (LoRA on fluent
narration) is what removes the conversational/halting character and gives the
composed "narrator" delivery — the same move Sesame made for its demo voices. A
tuned 1B won't fully equal their hosted demo (a larger fine-tuned variant), but
it's the best this hardware does without the 8B-class cost already ruled out.

---

## 2026-06-10 — Match MisoTTS-8B-class accuracy (engine upgrade + bench)

**Status: superseded (same day)** — direction changed to staying on CSM-1B
(engine swap judged too expensive; Qwen-TTS/Kokoro already tried and unwanted).
See the entry above. Kept for the MLX model research below.

### Context

readback currently reads articles with **CSM-1B** (csm-mlx, bf16, RTF ~0.8 on M5).
The goal is output quality/accuracy comparable to **MisoTTS-8B** (misolabs.ai,
released Jun 3 2026), with everything staying local on the M5 Pro (18 CPU / 20
GPU cores, 48 GB unified, 1 TB).

**The pivotal finding: MisoTTS-8B IS the CSM architecture scaled up.** Per Miso's
blog + repo, it's a Llama-3.2-style ~7.7B backbone + ~300M depth decoder over the
**Mimi codec** (32 RVQ codebooks) — the exact design of the CSM-1B readback runs
today, 8× bigger. Modified-MIT license, English-only, voice cloning via reference
`Segment`s (same concept as our `CsmVoicePrompt`). Reference impl is CUDA-only
(24 GB VRAM bf16), **but `mlx-audio` ≥0.4.4 supports CSM/MisoTTS natively** and
mlx-community ships ready quants — so the target model itself is runnable on this
Mac. The codebase already anticipates this: `Synthesizer`'s docstring promises "a
future engine (e.g. a MisoTTS-8B MLX port) is a factory change, not a server
rewrite", and `TTSConfig.engine` is a one-value enum waiting for a second engine.

Sample analysis (`/Users/mks/Desktop/sample`): the 2 WAVs are readback outputs
(24 kHz mono, 2:46 + 1:29); the 3-min screen recording is the quality reference.
Silence scan found **zero pauses ≥0.35 s** — `_tidy_silence` already fixed pacing,
so the remaining gap is **model-level naturalness + word accuracy**, i.e. a model
upgrade, not more post-processing.

### Verified facts (HF API + PyPI, 2026-06-10)

| Item | Fact |
|---|---|
| `MisoLabs/MisoTTS` (original) | 32.75 GB fp32 safetensors (~8.2B params), tags: sesame/mimi/llama |
| `mlx-community/MisoLabs-MisoTTS-8bit` / `-bf16` | MLX conversions exist (≈9 GB / ≈16.4 GB) |
| `mlx-community/MOSS-TTS-8B-8bit` | 10.48 GB, Apache-2.0, runs via mlx-audio today; card claims **1.84% EN WER**, zero-shot cloning, up to 1 h continuous synthesis |
| `mlx-community/Kokoro-82M-bf16` | ~0.3 GB, 54 preset voices, mlx-audio's flagship-fast model |
| `mlx-audio` 0.4.4 (Jun 6 2026) | requires **mlx≥0.31.1, mlx-lm≥0.31.1, transformers≥5.5**; one `generate()` API across all of the above incl. cloning models |
| Project venv today | mlx 0.26.5 / mlx-lm 0.26.4 / csm-mlx 0.2.3 (git dep) → **mlx upgrade required**; bonus: mlx ≥0.30 uses the M5 GPU neural accelerators (faster prefill — helps the ~10 s ref-clip prefill and an 8B backbone) |
| Memory budget | worst case: 8B-8bit engine ~10 GB + Ollama nemotron-4B (separate proc ~3 GB) + mlx-whisper bench ~1.5 GB ≪ 48 GB. Even Miso bf16 (16.4 GB) is viable |

### Recommended models (the menu)

1. **MisoTTS-8B** — `mlx-community/MisoLabs-MisoTTS-8bit` (9 GB; `-bf16` at 16.4 GB
   for max quality). The literal target sound. Same CSM family → our `kay` clone
   clip + ref-text machinery maps 1:1. English-only, modified-MIT. Risk: the MLX
   path is days old. Expected RTF ~1–3× (spike measures).
2. **MOSS-TTS-8B** — `mlx-community/MOSS-TTS-8B-8bit` (10.5 GB). The safe 8B:
   Apache-2.0, published 1.84% EN WER (the "accuracy" metric, better than most
   commercial TTS), zero-shot cloning, 20+ languages, 1-hour single-pass mode
   (future: whole-article-in-one-call, no chunk seams).
3. **Kokoro-82M** — `mlx-community/Kokoro-82M-bf16` (0.3 GB). The speed/stability
   floor: near-instant (RTF ≪0.2), bulletproof pronunciation, 54 preset voices.
   No cloning (kay won't exist here). Ideal "fast mode" + bench sanity anchor.

(Considered, not recommended: VibeVoice-1.5B — long-form king but research-only
license and patchy MLX support; Chatterbox — conversational, short-utterance
focus. Both reachable later through the same adapter if wanted.)

**CSM-1B stays** as the 4th engine (default until the bench says otherwise).

### Implementation

#### Phase 0 — Spike: prove the models run (before any refactor)
1. Snapshot `pip freeze > /tmp/readback-freeze.txt` (rollback path). Check disk free.
2. In the project venv: `pip install mlx-audio` (pulls mlx/mlx-lm 0.31.x,
   transformers 5.x). **Smoke-test CsmEngine still works** under the new mlx
   (`Synthesizer(Config.load().tts).synthesize("…")`).
3. CLI smoke each candidate, timing wall-clock vs audio seconds (RTF):
   `python -m mlx_audio.tts.generate --model <id> --text "<200-word passage>"`
   for MisoLabs-MisoTTS-8bit, MOSS-TTS-8B-8bit, Kokoro-82M-bf16.
4. Verify cloning args on Miso/MOSS (ref audio + ref text → reuse
   `voice/voice_kay_default.wav`).
5. Gate: a model that won't run or is unusably slow (RTF > ~4 even at 8-bit) is
   dropped; optionally self-convert 4/6-bit via `python -m mlx_audio.convert`.

#### Phase 1 — Accuracy bench harness (`scripts/bench_tts.py`)
The objective definition of "match accuracy": WER measured by local ASR.
- Add `bench` extra in `pyproject.toml`: `mlx-whisper`, `jiwer`.
- Script: fixed test passage (~600 words: numbers, names, acronyms, quotes) →
  reuse `chunk_text` + `_tidy_silence` + gap-join from `readback/reader/speak.py`
  → write `bench_out/<engine>.wav` → transcribe with mlx-whisper
  (`mlx-community/whisper-large-v3-turbo`) → jiwer WER/CER (punctuation/case
  normalized) → print a markdown table: **engine | WER | CER | RTF | peak RAM**.
- `--transcribe-only` mode to baseline the two Desktop sample WAVs (current CSM
  output) for the before/after story.
- Output WAVs double as the listening A/B kit vs the screen-recording reference.

#### Phase 2 — Engine layer: `MlxAudioEngine` (one adapter, three models)
- `readback/tts/mlx_audio_engine.py`: same proven shape as `CsmEngine`
  (`csm_engine.py`): single-thread `ThreadPoolExecutor` owning ALL mlx work
  (MLX thread-binding rule), lazy `_load_impl` (mlx_audio `load_model`),
  `synthesize` → numpy float32 mono @ engine sample rate (24 kHz for all three),
  voice handling:
  - preset voices (Kokoro voice ids) from config,
  - clone voices reusing the existing `CsmVoicePrompt` shape (`wav` + `ref_text`)
    mapped to mlx-audio's ref-audio args (Miso/MOSS).
  - `synthesize_stream`: trivial fallback (yield the one batch result) — the
    reader only uses batch.
- `readback/config.py`: `TTSConfig.engine: Literal["csm","mlx_audio"]`; new
  `MlxAudioConfig{model, speaker, temperature?, voices: list[CsmVoicePrompt]}`;
  `TTSConfig.active` dispatches on engine (server contract `active.speaker`
  unchanged); `Config.load()` resolves `mlx_audio.voices[].wav` like csm's.
- `readback/tts/synthesizer.py`: the promised factory — pick engine class from
  `cfg.engine`.
- Voice list without loading models: add `voices_for_config(tts_cfg)` (dispatching
  helper next to the engines) and use it in `web/server.py` `/api/config` + the
  WS config seed (today they call `voices_for(cfg.tts.csm)` directly —
  `server.py:215,227`).
- `reader/speak.py`: `chunk_text(text, max_chars=280)` param; `synthesize_article`
  passes `getattr(synth, "max_chunk_chars", 280)` so engines can widen later
  (MOSS long-context). Keep `_tidy_silence` for every engine.

#### Phase 3 — Config presets, docs, version
- `config.yaml`: commented presets — switch engine by uncommenting:
  `engine: "mlx_audio"` + `mlx_audio.model:` one of the three ids (+ kay clone
  entry under it for Miso/MOSS). Engine choice = config + restart (one resident
  model; no multi-engine RAM stacking).
- `pyproject.toml`: add `mlx-audio>=0.4.4` (main dep), `bench` extra; csm-mlx git
  dep stays (runtime CSM + the LoRA finetune pipeline).
- README + CLAUDE.md + ARCHITECTURE.md: engine matrix (size / license / cloning /
  measured RTF + WER from the bench), model-download sizes, note that Miso's
  torch repo watermarks output (SilentCipher) but the MLX path may not — keep the
  consent note for cloning.
- Version bump → **v0.9.0** in `pyproject.toml`, `readback/__init__.py`,
  `web/frontend/package.json` (no frontend code changes needed — the picker is
  fed by the server's voice list).

#### Phase 4 — Tune + pick the default
- Run the full bench; if the 8B winner's RTF is painful, bench its 4-bit/6-bit
  self-conversion (WER re-checked — quantization can hurt prosody).
- CSM cheap wins while benching (no code): `precision: fp32` (RTF ~1.4),
  temperature 0.6, optionally a longer 5–8 s kay ref clip (csm-voice skill).
- Deliverable: bench table + `bench_out/*.wav` to listen, then set the winner as
  the shipped `config.yaml` default.

### Files
- **New**: `readback/tts/mlx_audio_engine.py`, `scripts/bench_tts.py`
- **Edit**: `readback/config.py`, `readback/tts/synthesizer.py`,
  `readback/web/server.py` (2 call sites), `readback/reader/speak.py` (chunk
  param), `config.yaml`, `pyproject.toml`, README/CLAUDE/ARCHITECTURE,
  `readback/__init__.py`, `web/frontend/package.json` (version only)

### Verification
1. Phase-0 spike outputs audible WAVs for all surviving models; CSM still works
   post-upgrade.
2. `scripts/bench_tts.py` table on M5 Pro: target **WER ≤ ~2–3%** for the chosen
   default (vs baseline transcription of the current sample WAVs), RTF recorded.
3. End-to-end smoke per engine (config swap + restart): paste an article URL →
   Full mode → player + download work; **cancel mid-synthesis works** (the
   `should_stop` per-chunk abort is engine-agnostic in `synthesize_article`).
4. Summary mode unaffected (Ollama path untouched).
5. Listening A/B: bench WAVs vs the Desktop screen-recording reference.

### Risks & fallbacks
- **mlx 0.26→0.31 may break csm-mlx 0.2.3** → update csm-mlx from git main; worst
  case run CSM through mlx-audio too (it supports CSM) and keep csm-mlx only for
  the finetune pipeline.
- **mlx-audio's MisoTTS path is ~4 days old** → MOSS-TTS-8B is the proven-port
  fallback; same adapter, zero extra code.
- **8B RTF disappoints** → 4-bit convert, or ship Kokoro as fast default with the
  8B as the "quality" preset; offline-reader UX (progress bar + cancel) already
  absorbs slow synthesis.
- **Dep solver conflicts** (transformers 5.x) → restore from the freeze snapshot;
  retry in a fresh venv to isolate.
