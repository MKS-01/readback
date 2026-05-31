# Research: local-tts voice-pipeline revamp (open models on Apple Silicon)

> Living research log. Status tags: ✅ confirmed · ⏳ partial · ❓ verify in-impl.
> Companion to [PLAN.md](PLAN.md). Last pass: 2026-06-01.

## 0. Guiding constraints (the lens for every choice)

- **On-device only.** Project premise (CLAUDE.md): "running entirely on-device."
  Any cloud-API dependency breaks that — may be *offered*, never required/default.
- **Hardware (dev + test machine): 14" MacBook Pro (Space Black), Apple M5 Pro —
  18-core CPU, 20-core GPU, 16-core Neural Engine, 48 GB unified memory, 1 TB SSD.
  NO CUDA.** MPS exists but CPU often wins for small models. Rule out CUDA-only;
  prefer **MLX (Metal, → 20-core GPU)** or CPU-friendly runtimes (CTranslate2,
  ONNX, GGUF/Ollama). **Accelerator mapping for this revamp:**
  - **20-core GPU (MLX/Metal):** Parakeet ASR, Qwen3-TTS (mlx-audio), Ollama/Nemotron.
  - **16-core Neural Engine (CoreML):** best home for **Smart-Turn** — a CoreML
    build exists and the ANE makes the ~12 ms ONNX figure even cheaper; consider
    CoreML over plain `onnxruntime` CPU if wiring is easy.
  - **18-core CPU:** Kokoro TTS (fastest there), webrtcvad, `onnxruntime` fallback.
  - **48 GB unified:** ample — Nemotron-4b (2.8 GB) + Parakeet (~2.5 GB) + Kokoro
    (~0.3 GB) + optional Qwen3-TTS-0.6B all resident at once with room to spare.
  - **1 TB SSD:** fine for downloads, but note Ollama already holds ~75 GB of
    other models (gemma4:26b, qwen3.6, qwen3.5:27b, …) — keep an eye on free space.
- **Real-time target.** ~800 ms voice-to-voice is the cloud ideal
  (voiceaiandvoiceagents.com); fully-local on M-series realistically ~1.2–2.5 s
  to first spoken word. Per-stage latency is the binding constraint.
- **Keep it reversible & web-only.** One front-end (`web/static/`), FastAPI + WS.

## 1. Reference material

- **Daily.co — Building voice agents with NVIDIA open models** ✅ Stack:
  Nemotron-Speech-Streaming-EN 0.6B ASR → Nemotron-3-Nano-30B LLM → Magpie TTS,
  glued by **Pipecat** + a **Smart-Turn** model (CPU). **Requires RTX 5090 / DGX
  Spark Blackwell + CUDA 13** → not Mac-runnable as-is; we adopt Apple-Silicon
  equivalents of the same *architecture*.
- **voiceaiandvoiceagents.com — Illustrated Primer** ✅ Cascade STT→LLM→TTS still
  dominates; 800 ms target; turn detection (VAD + semantic); interruption
  handling; WebRTC > WebSocket for production.
- **NVIDIA Nemotron 3 (Ollama)** ✅ `nemotron3:33b` (multimodal) + Nemotron-3-Nano.

## 2. Current stack (verified by reading the code)

| Stage | Now | File |
|---|---|---|
| ASR | faster-whisper (CPU int8, **batch**) | `stt/transcriber.py` |
| LLM | Ollama `qwen3:4b` (streaming, sentence-split, `_strip_markdown`) | `llm/client.py` |
| TTS | Kokoro-82M (CPU, 24 kHz, `af_bella`) | `tts/synthesizer.py` |
| Turn | webrtcvad batch (8 speech-start / 25 silence-end) | `web/server.py` |
| UI | vanilla JS (`web/static/`), three.js orb | `web/static/*` |

Local env ✅: `.venv`, Python 3.11.15. Ollama running; **`nemotron-3-nano:4b`
already pulled** (2.8 GB, Q4_K_M, family `nemotron_h`), plus qwen3:4b etc.
`web/frontend/` is an **empty React scaffold** → ignore; live UI is `web/static/`.

## 3. Component research

### 3.1 ASR — NVIDIA Parakeet via `parakeet-mlx` ✅
- PyPI `parakeet-mlx` (senstella), Apple-Silicon/MLX, macOS 13+. NVIDIA Parakeet
  (TDT/RNNT/CTC). Perf: ~1 h audio in ~53 s → RTF ≪ 0.1. `ffmpeg` only for *files*.
- **API (confirmed):** `from parakeet_mlx import from_pretrained` →
  `m = from_pretrained("mlx-community/parakeet-tdt-0.6b-v2")` (English; `…-v3` = 25
  langs; also `…-1.1b`, `…-rnnt-0.6b`, `…-ctc-0.6b`). Batch:
  `m.transcribe("a.wav").text` (result → `.sentences[].tokens[].{text,start,end}`).
  **Streaming:** `with m.transcribe_stream(context_size=(256,256)) as s:
  s.add_audio(chunk); s.result.text`.
- ❓ Docs show only *file-path* input; **numpy float32 @16 k input + chunk
  format/size undocumented** → introspect installed pkg in Phase 1 (we feed raw
  PCM from the WS).

### 3.2 LLM — NVIDIA Nemotron via Ollama ✅ (model already pulled)
- `nemotron-3-nano:4b` present (Q4_K_M, `nemotron_h`). Alts:
  `NVIDIA-Nemotron-Nano-9B-v2`, `nemotron3:33b` (heavy multimodal).
- **Reasoning traces** (`<think>…</think>`, confirmed in GGUF builds). Handling
  (confirmed): **Ollama `think` boolean** on chat/generate — `message.thinking`
  carries the trace, `message.content` the answer
  (docs.ollama.com/capabilities/thinking). We already read only
  `chunk.message.content`, so set **`think=False`** + keep a defensive
  `<think>…</think>` strip for inline-tag GGUFs. (30B also has
  `ENABLE_NEMOTRON_3_NANO_THINKING=false` / `--hidethinking` / `/set nothink`.)
- ❓ Does `nemotron-3-nano:4b` actually think, and does the venv `ollama` client
  support `think=`? (bump pkg if not). Disabling reasoning slightly lowers
  hard-prompt accuracy — fine for chit-chat voice.

### 3.3 TTS — pluggable: Kokoro (default) + Qwen3-TTS (option) ✅
**Decision criterion: on-device, low latency, natural.**
- **Kokoro-82M (current, default)** ✅ — CPU, RTF ~0.15 (~500 ms/sentence),
  24 kHz, many voices, Apache-2.0, proven here. **Real-time baseline.**
- **NVIDIA Magpie 357M** ❌ — CUDA/Blackwell only; no Apple-Silicon path.
- **Qwen3-TTS** ✅ **viable on-device, opt-in** — github.com/QwenLM/Qwen3-TTS ·
  **Apache-2.0** · open-sourced **2026-01-22** (~11.7k★). **Open weights, NOT
  API-only** (DashScope optional; "-Flash/-Realtime" = the API product, not the
  open repo). Models (10 langs, streaming): `…-12Hz-{0.6B,1.7B}-{Base,CustomVoice,
  VoiceDesign}` + 12 Hz tokenizer/codec; discrete multi-codebook LM.
  - **Apple-Silicon path (community) ✅:** `mlx-audio` (Blaizzy) +
    `mlx-community/Qwen3-TTS-12Hz-*` weights; also CoreML / GGUF / ExecuTorch ports.
  - **mlx-audio API (confirmed):** `pip install mlx_audio`;
    `from mlx_audio.tts.utils import load_model` →
    `load_model("mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit")`;
    `from mlx_audio.tts.generate import generate_audio` →
    `generate_audio(model, text=…, lang_code="English", …)`; design via
    `model.generate_voice_design(text, instruct="female, British narrator")`;
    preset via `model.generate_custom_voice(text, speaker="Ryan", instruct="excited")`;
    `model.sample_rate`.
  - **⚠ Latency caveat (decisive):** mlx-audio ≈ **1,000 chars/min on M2** with
    **no streaming** exposed ⇒ ~seconds/sentence — far slower than Kokoro.
    ⇒ **Kokoro = real-time default; Qwen3-TTS = opt-in quality/voice-clone.**
    ❓ measure **0.6B** on the M5 in Phase 4 before exposing it.
  - *Aside:* Qwen also ships open **Qwen3-ASR-1.7B** — possible future full-Qwen
    stack; out of scope now.

### 3.4 Turn detection — Smart-Turn v3 (ONNX) ✅ feasible on M5
- `pipecat-ai/smart-turn` (open): **semantic** end-of-turn from raw waveform (not
  transcript), 14 langs. **v3 = ONNX, ~12 ms CPU inference** (Daily, "Smart Turn
  v3"); v2 = PyTorch (MPS); CoreML build exists.
- **Integration:** run **smart-turn-v3 ONNX directly via `onnxruntime`**
  (lightweight) rather than pulling the whole `pipecat` framework. Hybrid:
  webrtcvad pause-gate → Smart-Turn confirms end-of-turn (~8 s @16 k window →
  P(complete)); max-wait safety timeout fallback.
- ❓ Confirm v3 ONNX checkpoint id + input window/format in Phase 3.

## 4. Open questions — status

| # | Question | Status |
|---|---|---|
| 1 | Qwen3-TTS local on Apple Silicon? | ✅ yes (mlx-audio), but slow → opt-in |
| 2 | parakeet-mlx streaming API | ✅ `transcribe_stream`/`add_audio`/`.result` |
| 3 | Nemotron reasoning handling | ✅ `think=False` + `<think>` strip |
| 4 | Smart-Turn on Mac | ✅ v3 ONNX ~12 ms CPU via onnxruntime |
| 5 | numpy input to parakeet-mlx | ❓ verify Phase 1 (introspection) |
| 6 | real M5 latency (Parakeet, Nemotron-4b, Kokoro, Qwen3-TTS-0.6B) | ❓ measure Phase 1/4 (desk-research only for now) |

## 5. Recommended architecture (research-grounded)

```
mic (Int16 16k) ─ws─▶ Session
   ├ webrtcvad pause-gate (cheap)
   ├ Parakeet-MLX streaming ──▶ partial transcript ─ws─▶ live caption
   └ on pause → Smart-Turn v3 (ONNX ~12ms) ─complete?─▶ finalize transcript
        ▼
   Nemotron (Ollama, think=False) ─sentences─▶ TTS engine ─Float32 24k─▶ ws ▶ play
        TTS engine = Kokoro (default)  |  Qwen3-TTS (opt-in, mlx-audio)
```
- All Parakeet (MLX) calls on **one** worker thread (MLX/Metal not multi-thread safe).
- TTS behind a small engine interface (mirror the ASR-engine pattern) → selectable.

## 6. Confirmed design decisions (with user)

1. **Scope:** full revamp — ASR + LLM + turn-taking + TTS option.
2. **ASR:** replace faster-whisper **entirely** with Parakeet (MLX), **streaming**.
3. **Turn-taking:** streaming ASR + **Smart-Turn v3** (hybrid w/ webrtcvad pre-gate).
4. **LLM:** Nemotron (`nemotron-3-nano:4b`) with `think=False` + `<think>` strip.
5. **TTS:** **pluggable** — **Kokoro default** + **Qwen3-TTS opt-in**
   (mlx-audio, `0.6B-CustomVoice`).
6. **Validation:** **desk research only** now; **measure latency during Phase 1**
   (no installs/benchmarks before implementation is approved).

## 7. Latency budget (M5 estimate — to be MEASURED in Phase 1)

| Stage | Estimate (verify) |
|---|---|
| webrtcvad pause gate | ~250–700 ms (tunable) |
| Smart-Turn v3 decision | ~12 ms (CPU) |
| Parakeet streaming finalize | ~50–200 ms (most already streamed; RTF ≪ 0.1) |
| Nemotron-3-nano:4b first token | ~200–500 ms (4B Q4 — measure) |
| Kokoro first sentence | ~300–500 ms |
| **→ first spoken word** | **~1.2–2.0 s target (measure)** |
| Qwen3-TTS-0.6B first sentence | ❓ likely ≫ Kokoro; measure before exposing |

## 8. Sources

- Daily.co — NVIDIA open voice models: https://www.daily.co/blog/building-voice-agents-with-nvidia-open-models/
- Daily.co — Smart Turn v3 (12 ms CPU): https://www.daily.co/blog/announcing-smart-turn-v3-with-cpu-inference-in-just-12ms/
- Voice AI & Voice Agents primer: https://voiceaiandvoiceagents.com/
- Nemotron 3 (Ollama): https://ollama.com/library/nemotron3 · nano: https://ollama.com/library/nemotron-3-nano
- Ollama thinking docs: https://docs.ollama.com/capabilities/thinking
- parakeet-mlx: https://github.com/senstella/parakeet-mlx · docs: https://senstella-parakeet-mlx.mintlify.app/introduction
- Qwen3-TTS: https://github.com/QwenLM/Qwen3-TTS · weights: https://huggingface.co/collections/Qwen/qwen3-tts
- mlx-audio: https://github.com/Blaizzy/mlx-audio · macOS guide: https://mybyways.com/blog/qwen3-tts-with-mlx-audio-on-macos
- Smart-Turn: https://github.com/pipecat-ai/smart-turn · model: https://huggingface.co/pipecat-ai/smart-turn-v2
