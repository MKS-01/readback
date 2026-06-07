# Architecture — local-tts (v0.5.0)

How the pieces fit together and why. This is the system-level companion to
[CLAUDE.md](CLAUDE.md) (which holds implementation notes, gotchas, and exact
knobs) and [README.md](README.md) (user-facing). When in doubt about a specific
threshold or flag, CLAUDE.md is authoritative.

## 1. What it is

A fully **on-device** voice assistant served as a web app. The browser captures
mic audio and plays TTS audio; everything else runs locally on an Apple-Silicon
Mac. The pipeline is a **streaming cascade**:

```
speech ─▶ STT ─▶ turn detection ─▶ LLM ─▶ TTS ─▶ speech
         (Parakeet/Whisper)  (Smart-Turn)  (Ollama/Nemotron)  (CSM-1B)
```

Optional layers: function-calling **tools** (clock, web search) and an
**Obsidian** second-brain export. One process, one CLI (`local-tts`), one
WebSocket endpoint (`/ws`), one React UI.

## 2. High-level data flow

```
 ┌─────────┐  Int16 PCM 16k (binary WS)   ┌────────────────────────────────────┐
 │ Browser │ ───────────────────────────▶ │ FastAPI server · Session (per conn) │
 │  (mic)  │                              │                                      │
 │         │ ◀─────────────────────────── │  webrtcvad → utterance segmentation  │
 │ (orb +  │  Float32 PCM 24k (binary WS) │         │                            │
 │ caption)│ ◀─────────────────────────── │         ▼                            │
 │         │  JSON: phase/partial/turn/   │   ASR (Parakeet, streaming)          │
 │         │        transcript/config/... │           ──▶ partial captions       │
 └─────────┘                              │         │                            │
                                          │         ▼  on pause                  │
                                          │   Smart-Turn v3 (complete?) ──no──┐  │
                                          │         │ yes                      │  │
                                          │         ▼              keep listening │
                                          │   LLM (Ollama/Nemotron, streaming)   │
                                          │         │ sentences                  │
                                          │         ▼                            │
                                          │   TTS (CSM-1B) per sentence          │
                                          │         │ Float32 24k                │
                                          │         ▼                            │
                                          │   WS send_audio ─────────────────────┘
                                          └──────────────────────────────────────┘
                                  (on disconnect) ──▶ topic classifier ─▶ Obsidian markdown
```

The cascade is streaming end-to-end: partial captions appear *while you speak*,
and TTS for sentence N plays while the LLM is still generating sentence N+1.

## 3. Concurrency model (the important part)

The event loop must never block on a model. Work is spread across threads with
strict ownership rules. **MLX/Metal is not multi-thread safe** — its default GPU
stream binds to the first thread that touches the device — which dictates much of
this design.

| Thread / context | Owns | Notes |
|---|---|---|
| **asyncio event loop** | WS recv/send, control messages, VAD `_process_frame`, pipeline orchestration | Never runs a model inline; offloads via `to_thread` or queues |
| **ASR worker thread** (per session, `_asr_worker_loop`) | Orders mic frames → Parakeet streaming; emits partials; triggers finalize | One per session; talks to the Parakeet executor, not MLX directly |
| **Parakeet executor** (1 thread, in `ParakeetEngine`) | *All* Parakeet MLX work (load, batch, streaming feed/finalize) | `ThreadPoolExecutor(max_workers=1)`; public methods submit + block |
| **CSM executor** (1 thread, in `CsmEngine`) | *All* CSM-1B MLX work (load + synth) | Same single-thread pattern as Parakeet |
| **LLM producer thread** (per turn, via `to_thread`) | Streams Ollama → finished sentences onto an `asyncio.Queue` | Consumer races each `get()` against `interrupt_event` |
| **`to_thread` pool** | Whisper batch transcribe, Smart-Turn inference, model/voice/persona swaps | CPU-bound or onnx; thread-safe under their own locks |

Cross-thread handoffs back to the loop always go through
`loop.call_soon_threadsafe(...)` (partials, pipeline launch).

Why the executors: a model loaded on thread A and called from thread B raises
`RuntimeError: no Stream(gpu, 0) in current thread`. Pinning each MLX model to
one owned thread makes correctness independent of which caller invokes it (this
also fixed a latent crash in the batch transcribe path, which the server calls
from arbitrary `to_thread` pool threads).

## 4. Turn lifecycle (one spoken exchange)

1. **Capture.** Browser AudioWorklet downsamples mic to 16 kHz Int16, streams
   binary frames. Frames are **dropped** while a pipeline is running
   (`pipeline_task is not None`) or during the finalize window
   (`_awaiting_finalize`) — the sole speaker-bleed guard.
2. **Segment.** `_process_frame` runs webrtcvad: 8 speech frames (~240 ms) to
   start, frames accumulate into `utterance_frames`. For the streaming engine,
   each frame is also queued to the ASR worker, which emits `partial` captions.
3. **Pause → confirm.** After ~480 ms of silence, `_turn_is_complete()` asks
   **Smart-Turn** (off-loop). If `P(complete) < threshold`, keep listening
   (re-check every ~300 ms, hard cap at `turn.max_wait_sec`) and emit
   `turn:{state:waiting}`; otherwise end the turn.
4. **Finalize transcript.** The ASR worker finalizes the live stream (batch
   fallback if empty) and hands the text to the loop; `_dispatch_utterance` is
   the batch path kept for any future non-streaming engine. A phantom-utterance
   filter drops pure backchannels (echo/reverb/music false triggers) before
   launch.
5. **Generate.** `_run_pipeline(text=…)` appends the user turn, then a producer
   thread streams Nemotron output; a `_ThinkStripper` removes `<think>` spans and
   the sentence splitter yields complete sentences.
6. **Speak.** Each sentence → CSM-1B → Float32 24 kHz → `send_audio`. Every
   step races `interrupt_event` so **Skip** stops mid-sentence.
7. **Persist.** On disconnect, `SessionWriter.finalize` (background) classifies a
   topic and writes the Obsidian markdown; JSONL mirror deleted on success.

## 5. Component layers

### STT — Parakeet (`local_tts/stt/`)
`ASREngine` protocol (`base.py`) with one implementation behind a `Transcriber`
facade (the protocol/facade seam is kept so a second engine stays a one-file
addition; faster-whisper was the second engine through v0.6.0, removed in v0.7.0):
- **ParakeetEngine** (streaming) — NVIDIA Parakeet via `parakeet-mlx` on Metal.
  Both batch and streaming route through `transcribe_stream` / `add_audio`. Owns
  its MLX executor; buffers frames to `stream_chunk_ms`. `transcribe_file` backs
  clone-reference transcription (English-only). No hallucination guards — the
  server's phantom-utterance filter compensates.

The facade exposes `current_engine`, `engines_available` (`("parakeet",)`),
`models_for()`, `swap_engine`, `swap_model`, `transcribe`, `streaming_engine()`.
The server only talks to the facade.

### Turn detection (`stt/turn.py`)
`TurnDetector` runs Smart-Turn v3 ONNX (Whisper-tiny encoder + linear head) via
onnxruntime. Loaded once with **graceful fallback**: if it can't load, the
pipeline finalizes on VAD pause alone. Hybrid by design — cheap webrtcvad gates,
the semantic model only confirms.

### LLM (`llm/client.py`)
`LLMClient` wraps the Ollama client. `stream_response` yields complete sentences;
the tools branch does non-streaming tool-call probes (≤3 hops) then a final
stream. `think=False` + `_ThinkStripper` keep reasoning out of TTS. Personas are
snapshotted per response so a mid-stream swap can't split a prompt.

### TTS (`tts/`)
`CsmEngine` wraps `mlx-audio`'s CSM-1B (Sesame model; `generate(voice=…)` for
presets, `generate(ref_audio=…, ref_text=…)` for clones — one loaded model for
both), 24 kHz native, behind a `Synthesizer` facade that preserves the server's
surface. Owns its MLX executor. (Qwen3-TTS was replaced in v0.6.0; the facade
keeps a one-engine seam for a future MisoTTS-8B port.)

### Server (`web/server.py`)
`PipelineModels` is a lazy singleton holding the transcriber, LLM, synth, and
turn detector (loaded once at app startup). `Session` is per-WebSocket: VAD
segmentation, the ASR worker, control-message handlers (swaps, mute, interrupt,
text input), and pipeline orchestration. See CLAUDE.md for the WS message catalog.

### Frontend (`web/frontend/`)
React 18 + Vite + zustand. The audio engine, WS client, and three.js orb live as
singletons *outside* the React tree and push into the store, so re-renders never
tear down the socket or audio context. Settings holds the two-level ASR picker
(engine + model), voice/model/persona/tools pickers; captions render live
partials and the "still listening" turn hint.

## 6. Key invariants (don't break these)

- **MLX work stays on its engine's executor thread.** Never call an engine's
  `_impl` methods or raw `mx` ops from another thread.
- **Mic frames are dropped while speaking/finalizing.** This is the only
  speaker-bleed guard. If you ever accept audio during playback, replace it.
- **Swaps are refused mid-pipeline** and use atomic ref swaps under a lock, so an
  in-flight call finishes on its old model/voice/persona.
- **Smart-Turn and TTS engine failures degrade gracefully**, never crash the turn
  (VAD-only fallback; TTS errors surface as empty audio).
- **The WS `config` payload is the source of truth on each connect**; only
  `sttEngine`/`sttModel`/`voice`/`speed` are re-emitted from saved prefs.

## 7. Extension points

- **New ASR engine:** implement `ASREngine` (`stt/base.py`), register it in the
  `Transcriber` facade's engine map. Mirror the MLX-executor pattern if it's MLX.
- **New TTS engine:** implement the same shape as `CsmEngine`, select it via
  `TTSConfig.engine` in the `Synthesizer` factory.
- **New search provider:** implement `WebSearchProvider` and wire it in
  `tools/web_search.py:build_default_provider`.
- **New tool:** implement the `Tool` protocol (`tools/base.py`) and register it in
  `PipelineModels.load`.

## 8. Module map

```
local_tts/
├── config.py        Pydantic config (Ollama/STT/TTS/Turn/…); load() migrations
├── llm/client.py    LLMClient: streaming, think-strip, tools, personas
├── stt/
│   ├── base.py          ASREngine protocol + resample()
│   ├── parakeet_engine.py   ParakeetEngine (MLX, streaming) — sole ASR engine
│   ├── transcriber.py   Transcriber facade (model swap)
│   └── turn.py          Smart-Turn v3 detector (+ graceful fallback)
├── tts/
│   ├── csm_engine.py    CsmEngine (mlx-audio "sesame", MLX executor)
│   └── synthesizer.py   Synthesizer facade
├── tools/           Tool protocol, registry, clock, web_search
├── memory/          SessionWriter (JSONL mirror) + topic classifier
├── wakeword/        openWakeWord detector (backend retained, UI hidden)
└── web/
    ├── server.py    FastAPI app, PipelineModels, Session, WS protocol
    └── frontend/    React + Vite + zustand UI (built into static/dist)
```
