# PLAN — local-tts: streaming open-model voice pipeline (Apple Silicon)

> Revised after deep research — see [research.md](research.md) for evidence,
> exact APIs, sources, and the latency budget. All major decisions confirmed
> with the user. **Implementation is NOT started; awaiting go-ahead.**

## Context

`local-tts` is a fully **on-device** voice app (speak → STT → LLM → TTS → hear).
This revamp modernizes it toward open NVIDIA/Qwen voice models that actually run
on **Apple M5 Pro (48 GB, no CUDA)**, inspired by Daily.co's NVIDIA voice-agent
blog and the voiceaiandvoiceagents.com primer. The Daily stack itself is
Blackwell/CUDA-only, so we use the **Apple-Silicon-viable equivalents**.

## Target stack (best-of-open, all on-device)

| Stage | From | To |
|---|---|---|
| ASR | faster-whisper (batch) | **NVIDIA Parakeet via `parakeet-mlx`** (streaming) |
| Turn | webrtcvad batch | **webrtcvad pre-gate + Smart-Turn v3** (ONNX, ~12 ms CPU) |
| LLM | Ollama `qwen3:4b` | **NVIDIA Nemotron** `nemotron-3-nano:4b` (`think=False`) |
| TTS | Kokoro | **Pluggable: Kokoro (default) + Qwen3-TTS opt-in** (mlx-audio) |
| UI | vanilla JS `web/static/` | + live partial captions, ASR/TTS engine pickers |

## Architecture

```
mic (Int16 16k) ─ws─▶ Session
   ├ webrtcvad pause-gate (cheap speech/silence)
   ├ Parakeet-MLX streaming ──▶ partial transcript ─ws─▶ live caption
   └ on pause → Smart-Turn v3 (ONNX ~12 ms) ─complete?─▶ finalize
        ▼
   Nemotron (Ollama, think=False) ─sentences─▶ TTS engine ─Float32 24k─▶ ws ▶ play
        TTS engine = Kokoro (default)  |  Qwen3-TTS (opt-in, mlx-audio)
```
All Parakeet (MLX) calls run on **one** worker thread (MLX/Metal isn't
multi-thread safe); chunks in via a queue, partials out via
`loop.call_soon_threadsafe`.

## Implementation phases (each independently runnable; verify-in-phase)

> Per the "desk-research-only" decision, the few remaining unknowns are verified
> *inside* the relevant phase (introspection + a quick smoke test), not upfront.

### Phase 1 — Parakeet ASR engine (replace Whisper; batch first) + latency check
- Rewrite `stt/transcriber.py` to wrap `parakeet_mlx.from_pretrained(...)` behind
  the existing `Transcriber` surface (`SUPPORTED_MODELS`, `load`,
  `transcribe(audio, sr)`, `_resample`, swap-lock). Default
  `mlx-community/parakeet-tdt-0.6b-v2`.
- **Verify in-phase:** does `transcribe()` accept a numpy float32 @16 k array, or
  only a path? (introspect the installed pkg; if path-only, write the PCM window
  to an in-memory/temp wav). **Measure** first-word latency vs old Whisper.
- Deps: add `parakeet-mlx`. **Checkpoint:** UI works with Parakeet (still batch).

### Phase 2 — Streaming ASR + live partial transcripts
- Add to `Transcriber`: `start_stream()/feed(chunk)/partial_text/finalize()` over
  `m.transcribe_stream(context_size=(256,256))` (`add_audio`, `.result.text`).
- Rework `Session` (`web/server.py`): a dedicated ASR worker thread consumes the
  audio queue and feeds the stream; emit `{"type":"partial","text":…}` on each
  interim result. `web/static/{app.js,index.html}`: render the live partial in the
  INPUT caption (replace-in-place; promote to final on turn end).
- **Checkpoint:** words appear live while speaking.

### Phase 3 — Smart-Turn v3 turn detection
- New `stt/turn.py` — `TurnDetector` running **smart-turn-v3 ONNX** via
  `onnxruntime` (CPU) directly (avoid pulling all of `pipecat`).
  `is_complete(audio_window) -> bool` over a ~8 s @16 k window.
- In `Session`: webrtcvad pause → `TurnDetector` confirms end-of-turn (else keep
  listening); max-wait safety timeout. New `TurnConfig`. **Graceful fallback:** if
  the ONNX model can't be sourced, finalize on VAD pause alone (pipeline still works).
- **Verify in-phase:** v3 ONNX checkpoint id + input format. Deps: `onnxruntime`.
- **Checkpoint:** mid-sentence pauses don't cut you off; reply fires at true end.

### Phase 4 — LLM → Nemotron + reasoning handling + Qwen3-TTS engine
- LLM: default `cfg.ollama.model = "nemotron-3-nano:4b"` (already pulled). In
  `llm/client.py`: pass **`think=False`** to `ollama.chat(...)` (bump the `ollama`
  python pkg if the venv's is too old) AND keep a defensive `<think>…</think>`
  strip so reasoning is never sentence-split/TTS'd.
- TTS engine abstraction: introduce a tiny TTS interface; keep Kokoro
  `Synthesizer` as the default engine; add `tts/qwen.py` wrapping **mlx-audio**
  (`load_model("mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit")`,
  `generate_audio(...)` / `generate_custom_voice(...)` → float32 @ `model.sample_rate`,
  resample to 24 k for the WS contract). Factory selects by config.
- **Verify in-phase:** Nemotron-4b thinking behavior; **measure Qwen3-TTS-0.6B
  latency on M5** before exposing it as a real-time choice.
- Deps: `mlx-audio`. **Checkpoint:** Nemotron replies spoken cleanly (no `<think>`);
  TTS engine swappable Kokoro↔Qwen3-TTS.

### Phase 5 — UI + protocol wiring for the new pickers
- WS: `config` message carries `stt_model`/`stt_models_available` (Parakeet ids)
  and `tts_engine`/`tts_engines_available`; add `set_tts_engine` (+ reuse the
  mid-pipeline guard from `_handle_stt_swap`). Optional `{"type":"turn","state":…}`.
- `web/static/`: ASR (Parakeet) info + **TTS engine selector** (Kokoro / Qwen3-TTS),
  partial-caption rendering, optional turn indicator.
- **Checkpoint:** settings panel switches TTS engine live.

### Phase 6 — Cleanup, config, docs, version
- `pyproject.toml`: **remove** `faster-whisper`; add `parakeet-mlx`, `mlx-audio`,
  `onnxruntime`; bump `ollama`. Keep `torch`/`torchaudio` (Kokoro).
- `config.py`: `WhisperConfig` → `ParakeetConfig`; add `TurnConfig` and a
  `TTSConfig{engine: "kokoro"|"qwen", kokoro, qwen}`; default ollama model
  `nemotron-3-nano:4b`. Update `cfg.whisper` references in `server.py`.
- `config.yaml`: `whisper:` → `parakeet:`, add `turn:` + `tts:`; set the new model.
- Update `CLAUDE.md` (architecture, STT/TTS sections, model picks, latency budget)
  and `README.md` changelog → **v0.4.0**.

## Dependencies & models (all on-device)
- `pip install parakeet-mlx mlx-audio onnxruntime` (+ bump `ollama`). MLX/CoreML
  are Apple-Silicon native; `onnxruntime` ships a macOS arm64 wheel.
- First use downloads weights lazily: Parakeet ~2.5 GB; Qwen3-TTS-0.6B (only if
  selected); Smart-Turn v3 (small). `nemotron-3-nano:4b` already pulled.

## Risks / verify (folded into phases)
- parakeet-mlx numpy input (P1) · Smart-Turn v3 ONNX id/format (P3) · Nemotron-4b
  thinking + `ollama` `think=` support (P4) · Qwen3-TTS-0.6B M5 latency (P4) ·
  MLX single-thread discipline (P2). Each has a stated fallback.

## Verification (end-to-end)
1. `local-tts web` → speak → live **partial** caption (P2), Parakeet transcript.
2. Pausing mid-sentence doesn't cut you off; reply at true turn end (P3).
3. Nemotron reply spoken with **no** `<think>` text (P4).
4. Settings: switch **TTS engine** Kokoro↔Qwen3-TTS; switch ASR model (P5).
5. Interrupt/Skip still stops playback instantly (unchanged path).
6. `grep -ri faster.whisper local_tts/ pyproject.toml` → none (P6).

## References
See [research.md §8](research.md) for the full source list (Daily.co, Smart-Turn
v3, voiceaiandvoiceagents, Nemotron/Ollama, parakeet-mlx, Qwen3-TTS, mlx-audio).
