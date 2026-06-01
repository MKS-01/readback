# PLAN — local-tts: dual-ASR + dual-TTS streaming voice pipeline (Apple Silicon)

> Revised plan. Supersedes the original "replace Whisper / Qwen3-TTS opt-in"
> draft. `research.md` was deleted (outdated) — its sources are folded into
> §References below. Decisions confirmed with the user.

## Context

`local-tts` is a fully **on-device** voice app (speak → STT → LLM → TTS → hear),
web-only (FastAPI + WebSocket + React). This revamp modernizes it toward open
NVIDIA/Qwen voice models that run on **Apple M5 Pro (48 GB, no CUDA)**, inspired
by Daily.co's NVIDIA voice-agent stack and the
[Voice AI & Voice Agents primer](https://voiceaiandvoiceagents.com/). Daily's
stack is Blackwell/CUDA-only, so we adopt the **Apple-Silicon-viable
equivalents** of the same architecture.

### Key decisions (revised)
- **ASR is pluggable, not a replacement.** Keep **both** Parakeet (NVIDIA, MLX)
  and Whisper behind an `ASREngine` abstraction, toggleable from Settings.
  **Default = Parakeet.** Parakeet is streaming-capable; Whisper stays batch.
- **TTS is pluggable.** Add **Qwen3-TTS (mlx-audio) as the default** with
  **Kokoro as the fallback/switch** — both an explicit Settings switch and an
  automatic fallback to Kokoro if Qwen3-TTS can't load. ⚠ Qwen3-TTS has no
  streaming and is much slower than Kokoro; **measure on M5 before trusting it as
  the real-time default** (Phase 4b).
- **LLM default = `nemotron-3-nano:4b`** (NVIDIA); `nemotron3:33b`, qwen3, etc.
  stay selectable (the picker already lists every pulled Ollama model). Real work
  is `think=False` + `<think>` stripping.
- **Turn detection** = webrtcvad pre-gate + **Smart-Turn v3** (ONNX), with
  graceful VAD-only fallback.

### voiceaiandvoiceagents.com coverage
Cascade STT→LLM→TTS (kept); ~800 ms voice-to-voice ideal → ~1.2–2.0 s realistic
fully-local target (per-stage budget below); turn detection = VAD + semantic
(Phase 3); interruption/barge-in (existing `interrupt_event` race, kept);
WebRTC > WebSocket noted as a future track only (this project stays WS).

## Target stack

| Stage | Now | After |
|---|---|---|
| ASR | faster-whisper (batch, hardcoded) | **Pluggable: Parakeet-MLX (default, streaming) + Whisper (batch)** |
| Turn | webrtcvad batch | **webrtcvad pre-gate + Smart-Turn v3** (ONNX, graceful fallback) |
| LLM | Ollama `qwen3:4b` | **`nemotron-3-nano:4b`** (`think=False` + `<think>` strip); others selectable |
| TTS | Kokoro (hardcoded) | **Qwen3-TTS (mlx-audio, 24 kHz)** — Kokoro removed for now (dep conflict; user call) |
| UI | React pickers | + **two-level ASR engine+model picker**, **TTS engine selector**, live partial captions, turn indicator |

## Architecture

```
mic (Int16 16k) ─ws─▶ Session
   ├ webrtcvad pause-gate (cheap speech/silence)
   ├ [Parakeet] streaming ASR worker thread ──▶ partial ─ws─▶ live caption
   │  [Whisper]  buffer frames → batch transcribe at turn end (no partials)
   └ on VAD pause → Smart-Turn v3 (ONNX) ─complete?─▶ finalize transcript
        ▼
   Nemotron (Ollama, think=False, <think> stripped) ─sentences─▶ TTS engine ─F32 24k─▶ ws ▶ play
        TTS engine = Qwen3-TTS (default, mlx-audio)  |  Kokoro (fallback/switch)
```
All Parakeet (MLX) calls run on **one** worker thread (MLX/Metal isn't
multi-thread safe). The existing "drop mic frames while `pipeline_task is not
None`" gate in `web/server.py` is the only speaker-bleed guard and must stay.

## Implementation phases

### ✅ Phase 1 — ASR engine abstraction + Parakeet (batch) default; Whisper retained  — DONE
- `stt/base.py`: `ASREngine` Protocol + shared `resample()`.
- `stt/whisper_engine.py`: `WhisperEngine` (moved faster-whisper code verbatim —
  all hallucination guards intact). `stt/parakeet_engine.py`: `ParakeetEngine`
  wrapping `parakeet_mlx.from_pretrained`.
- `stt/transcriber.py`: `Transcriber(STTConfig)` facade — `current_engine`,
  `engines_available`, `models_for(engine)`, `swap_engine`, `swap_model`,
  `transcribe`. Server talks only to the facade.
- `config.py`: `ParakeetConfig` + `STTConfig{engine, whisper, parakeet}` (default
  `parakeet`); legacy top-level `whisper:` migrated into `stt.whisper` at load.
- `web/server.py`: `Transcriber(cfg.stt)`; config payload sends
  `stt_engine`/`stt_engines_available` + active-engine model list; added
  `set_stt_engine` handler (`_handle_stt_engine`).
- `pyproject.toml`: added `parakeet-mlx`; kept `faster-whisper`.
- **Verified:** parakeet-mlx `transcribe()` is file/ffmpeg-only, but
  `StreamingParakeet.add_audio(mx.array)` takes raw 1-D PCM → we route batch
  through `transcribe_stream`. End-to-end (Kokoro phrase → ASR):
  **Parakeet 1097 ms (RTF 0.235), Whisper medium 2861 ms (RTF 0.612)**, both
  transcribe correctly. `ollama` 0.6.2 already supports `think=` (no bump).

### ✅ Phase 2 — Parakeet streaming + live partial transcripts (Whisper stays batch)  — DONE
- `ParakeetEngine`: `start_stream()/feed(chunk)/partial_text/finalize()` over
  `transcribe_stream` (`add_audio`, `.result.text`). add_audio underflows on
  sub-~100 ms chunks, so the engine buffers mic frames to `stream_chunk_ms`
  (default 320 ms) before each encoder step.
- **MLX threading fix (important):** MLX binds its GPU stream to the thread that
  first touches the device, so cross-thread calls raise "no Stream(gpu, 0)".
  `ParakeetEngine` now owns a **single-thread executor** and runs ALL MLX work
  (load, batch transcribe, streaming) on that one thread. This also fixed a
  latent Phase 1 bug — the real server calls `transcribe()` via `to_thread` pool
  threads, which would have hit the same error.
- `Session`: dedicated ASR worker thread (`_asr_worker_loop`) feeds the stream
  when `supports_streaming`, emits `{"type":"partial","text":…}` via
  `call_soon_threadsafe`, and on VAD silence-end finalizes → launches the
  pipeline with the streamed text (batch fallback if empty). `_awaiting_finalize`
  gate blocks late frames. Whisper path untouched (batch).
- Frontend: `partialCaption` in the store; rendered dimmed/italic in the INPUT
  slot, replace-in-place, cleared/promoted on final transcript or idle.
- **Verified:** engine streaming accurate (word-by-word partials, correct final);
  Session integration test emits 59 partials and launches the pipeline with the
  finalized text; cross-thread batch + engine swap to Whisper both work; frontend
  builds (tsc + vite). Note: the VAD start-gate still drops the first ~240 ms
  (pre-existing, affects batch too; masked by natural leading silence).
- **Checkpoint:** words appear live on Parakeet; Whisper unchanged.

### ✅ Phase 3 — Smart-Turn v3 turn detection (hybrid, graceful fallback)  — DONE
- `stt/turn.py` `TurnDetector` — pipecat-ai `smart-turn-v3.2-cpu.onnx` (Whisper-
  tiny encoder + linear head, ~8M params) via `onnxruntime` (CPU). Contract:
  `WhisperFeatureExtractor(chunk_length=8, do_normalize=True)` → `input_features`
  (1,80,800) over the **last 8 s**; output sigmoid `P(turn complete)`; ≥0.5 ends.
  `probability()`/`is_complete()`; lazy load raises `TurnDetectorUnavailable`.
- `PipelineModels.load`: loads the detector once with graceful fallback (logs +
  `turn_detector=None` → VAD-only) when `turn.enabled` and the model can't load.
- `Session._process_frame`: at the webrtcvad pause (`SILENCE_FRAMES_TO_END`),
  `_turn_is_complete()` runs Smart-Turn (off-loop via `to_thread`), re-checks
  every `TURN_RECHECK_FRAMES` (~300 ms), and force-ends at `turn.max_wait_sec`.
  If incomplete, keeps listening (same utterance continues through the pause) and
  emits `{"type":"turn","state":"waiting"}`. New `TurnConfig`.
- Deps: promoted `onnxruntime` to core; added `transformers` (feature extractor).
- **Verified:** model returns ~0.98 on complete utterances, 0.26 on a trailing
  "um, well", ~7-12 ms inference; deterministic gate test holds through a
  mid-thought pause and ends once at turn end; `detector=None` cleanly falls back
  to VAD-only.

### ✅ Phase 4 — LLM → Nemotron default + reasoning handling  — DONE
- Default `ollama.model = "nemotron-3-nano:4b"` (config.yaml + `OllamaConfig`).
- `think=False` on all three `chat(...)` calls in `llm/client.py` (ollama 0.6.2
  supports it — no bump). New `_ThinkStripper` (stateful, withholds a trailing
  fragment that could be a split `<think>`/`</think>` tag) applied to both
  streaming paths; `strip_think()` one-shot for the non-streaming tool probe.
- **Verified:** stripper unit tests pass (split tags, char-by-char, unclosed,
  and `3 < 4 … 5 > 2` not false-matching). Live against Ollama: nemotron-3-nano
  returns clean output, **no `<think>`**, no error; 33b/qwen3 still selectable.
- **Caveat:** `qwen3:4b` ignores `think=False` and verbalizes its reasoning as
  *untagged* prose (model-specific; no stripper can catch untagged text). Only
  affects that non-default model — the default NVIDIA model is clean.

### ✅ Phase 4b — Qwen3-TTS (Kokoro removed)  — DONE  *(scope changed by user)*
- **Dependency conflict found:** mlx-audio requires `transformers>=5.5`, whose
  import chain needs `torch.distributed.tensor.device_mesh` (torch≥2.5) — but the
  project pins torch 2.4 for stability, and transformers 5.x breaks Kokoro
  (`AlbertModel`). Resolution: Qwen3-TTS **runs fine on transformers 4.49**
  (its `>=5.5` pin is conservative), so we pin `transformers<5` and keep torch 2.4.
- **User decision mid-phase: remove Kokoro, Qwen3-TTS only for now.** So there is
  no TTS engine abstraction with two engines — `Synthesizer(TTSConfig)` is a thin
  facade over a single `QwenEngine` (seam kept for re-adding Kokoro later).
- `tts/qwen_engine.py` `QwenEngine`: mlx-audio
  `load_model("…Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit")` +
  `generate_custom_voice(text, speaker, instruct)` → float32 @ **24 kHz**
  (native; no resample). MLX single-thread → **owns a 1-thread executor** like
  Parakeet. 9 preset speakers (`SUPPORTED_VOICES`); `swap_voice` is instant (just
  a per-call arg). Warms the graph at `load()`.
- `config.py`: `QwenTTSConfig` + `TTSConfig{engine:"qwen", qwen}`; dropped the
  `kokoro` Config field (legacy `kokoro:`/`whisper:` blocks dropped at load).
  `config.yaml`: `kokoro:` → `tts:`. Server `cfg.kokoro.*` → `cfg.tts.qwen.*`.
- Deps: added `mlx-audio`, pinned `transformers<5`, removed `kokoro`/`misaki`.
- **Measured on M5:** cold first sentence ~2.4 s (warm-up), **warm RTF ~0.21**
  (664 ms for a 3.2 s clip), streaming first-chunk **126 ms** — viable real-time
  default; cross-thread synth + voice swap verified.
- **Caveat:** `speed` slider is a no-op for Qwen custom voice (only `generate()`
  takes speed); the 9 Qwen speakers replace the 20 Kokoro voices in the picker.

### ✅ Phase 5 — UI + protocol wiring (two-level ASR picker + partials)  — DONE
- (No TTS engine selector — TTS is Qwen-only after 4b.)
- Backend protocol (from P1/P3): `config` carries `stt_engine`,
  `stt_engines_available`, active-engine `stt_model(s)`, `turn_enabled`;
  `set_stt_engine` + `stt_engine {state}` messages.
- Store: `sttEngine`, `sttEnginesAvailable`, `turnEnabled`, `turnWaiting`.
  `App.tsx`: config reads the new fields; `stt_engine`/`turn` handlers;
  `onSwapSttEngine`; reconnect re-emits saved `sttEngine` (before model, guarded
  by `stt_engines_available`).
- `SettingsModal.tsx`: two-level ASR control — engine selector (Parakeet ★ /
  Whisper, styled like the speed picker, hidden when only one engine) + model
  `Picker` (server filters to the active engine); `STT_MODEL_LABELS` extended
  with Parakeet ids. Voice picker shows the 9 Qwen speakers.
- `Captions.tsx`: live partials (P2) + "Listening — go on…" while `turnWaiting`.
  `Header.tsx` `prettyVoice` title-cases `uncle_fu` → "Uncle Fu".
- Prefs `v9`→`v10` (+`sttEngine`, chained legacy migration).
- **Verified:** `npm run build` (tsc+vite) clean; in-process `TestClient` WS
  round-trip — config has the new fields, `set_stt_engine`→whisper returns the
  whisper model list.

### ✅ Phase 6 — config, deps, docs, version  — DONE
- `pyproject.toml`: added `parakeet-mlx` + `mlx-audio`; `onnxruntime` +
  `transformers<5` core; removed `kokoro`/`misaki`; `ollama>=0.6`; trimmed
  redundant onnxruntime from the `[wakeword]` extra.
- `config.py`: `STTConfig`/`ParakeetConfig`, `TTSConfig`/`QwenTTSConfig`,
  `TurnConfig`; default Nemotron; legacy `whisper:`/`kokoro:` dropped at load.
  `config.yaml`: `stt:` + `turn:` + `tts:` blocks.
- `CLAUDE.md` fully updated (intro, Hardware, Stack, Project Structure, Server
  pipeline, TTS/STT/Turn/LLM sections, WS protocol, reconnect, Frontend, Voice
  options, latency, install + dep note, gotchas, Version). `README.md` v0.5.0
  changelog. Versions bumped to **0.5.0** (pyproject, `__init__.py`,
  frontend `package.json`).
- **Verified:** `Config.load()` parses the new blocks; full-stack import clean;
  frontend builds.

## Latency budget (M5 — measured where noted)

| Stage | Value |
|---|---|
| webrtcvad pause gate | ~250–700 ms (tunable) |
| Smart-Turn v3 decision | ~12 ms (CPU) |
| Parakeet batch finalize (4.67 s clip) | **~1.1 s cold / RTF 0.235** (measured P1); streaming cuts this |
| Whisper medium batch (fallback engine) | **~2.9 s / RTF 0.612** (measured P1) |
| Nemotron-3-nano:4b first token | ~200–500 ms (measure P4) |
| Qwen3-TTS-0.6B first sentence (default) | ❓ likely ≫ Kokoro, no streaming — measure P4b |
| Kokoro first sentence (fallback) | ~300–500 ms |

## References (research.md deleted; sources captured here)
- Daily.co — NVIDIA open voice models: https://www.daily.co/blog/building-voice-agents-with-nvidia-open-models/
- Daily.co — Smart Turn v3 (12 ms CPU): https://www.daily.co/blog/announcing-smart-turn-v3-with-cpu-inference-in-just-12ms/
- Voice AI & Voice Agents primer: https://voiceaiandvoiceagents.com/
- Nemotron 3 (Ollama): https://ollama.com/library/nemotron-3-nano · Ollama thinking: https://docs.ollama.com/capabilities/thinking
- parakeet-mlx: https://github.com/senstella/parakeet-mlx
- Qwen3-TTS: https://github.com/QwenLM/Qwen3-TTS · mlx-audio: https://github.com/Blaizzy/mlx-audio
- Smart-Turn: https://github.com/pipecat-ai/smart-turn
