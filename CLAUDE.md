# local-tts — Project Context

A local voice conversation app similar to sesame.com, running entirely on-device.
Full voice loop: speak → STT → Ollama LLM → TTS → hear response.
Also supports text-in with voice-out mode.

## Hardware
- Apple M5 Pro, 48GB unified memory
- No CUDA. PyTorch MPS available, but **Kokoro runs faster on CPU** than MPS
  on this machine (iSTFT op falls back to CPU and transfer overhead dominates
  for an 82M-param model). Whisper also runs on CPU (CTranslate2 ARM NEON).

## Stack
- **LLM**: Ollama (already running locally, default model: `qwen3:8b`)
- **TTS**: Kokoro-82M (`hexgrad/Kokoro-82M`) — fast, near-human, runs on CPU
- **STT**: faster-whisper (`base.en`, CPU int8 mode, CTranslate2 ARM NEON)
- **Audio I/O**: sounddevice + webrtcvad-wheels
- **CLI/UI**: click + rich

## Architecture: 3-Thread Streaming Pipeline

```
[Thread 1: recorder]    mic → VAD → utterance → transcription_queue
[Thread 2: pipeline]    transcription_queue → Whisper → Ollama streaming
                        → sentence splitter → Kokoro TTS → playback_queue
[Thread 3: player]      playback_queue → sounddevice output

Text mode:              terminal input → pipeline_thread (skips recorder/Whisper)
Interrupt:              recorder detects sustained + loud speech during SPEAKING
                        → sets interrupt_event → player drains queue and stops
                        (gated by RMS threshold so speaker bleed doesn't self-interrupt)
```

## Project Structure

```
local-tts/
├── pyproject.toml
├── config.yaml                  # user-editable defaults
│
└── local_tts/
    ├── cli.py                   # click: run, list-devices, download-models
    ├── app.py                   # ConversationApp: thread topology + queue wiring
    ├── config.py                # Pydantic config loaded from config.yaml
    ├── state.py                 # AppState, Phase enum, shared threading events
    ├── audio/
    │   ├── recorder.py          # sounddevice InputStream + webrtcvad VAD loop
    │   └── player.py            # sounddevice playback, checks interrupt_event per chunk
    ├── stt/transcriber.py       # faster-whisper wrapper (CPU, int8)
    ├── llm/client.py            # ollama streaming + sentence boundary splitter
    ├── tts/synthesizer.py       # Kokoro KPipeline wrapper (CPU)
    └── ui/display.py            # rich Live: conversation history + phase status
```

## Critical Implementation Notes

### Kokoro TTS (tts/synthesizer.py)
- Use `kokoro.KPipeline(lang_code='a', device='cpu')` — CPU beats MPS on this 82M model
  because iSTFT (`aten::angle`) falls back to CPU and transfer overhead dominates.
- Default voice `af_heart`; other good options: `af_bella`, `af_sarah`, `am_michael`, `bf_emma`.
- KPipeline is stateless — no conversational context to manage (unlike CSM).
- First call downloads ~330MB model + voice pack from `hexgrad/Kokoro-82M`.
- Measured RTF on M5 Pro CPU: ~0.15× (≈500ms to synth a 3.4s sentence).

### VAD + Interrupt (audio/recorder.py)
- 16kHz, blocksize=480 (30ms frames — matches webrtcvad requirement)
- 10 speech frames → SPEECH; 23 silence frames (~700ms) → finalize utterance
- **Interrupt during SPEAKING phase requires BOTH:**
  - sustained speech ≥ `vad.interrupt_speech_ms` (default 900ms / 30 frames), AND
  - per-frame RMS ≥ `vad.interrupt_rms_threshold` (default 0.05)
- The RMS gate filters out the AI's own playback bleeding from speaker → mic.
  Speaker bleed typically ~0.01–0.03 RMS; direct user speech ~0.05–0.20.
- Set `vad.allow_interrupt: false` to disable interrupts entirely (use Ctrl+C
  or F4→text mode to cut off the AI). Recommended when running on laptop
  speakers without headphones.
- Audio callback emits `(pcm_bytes, rms_float)` tuples to the VAD loop.

### Sentence streaming (llm/client.py)
- Split on `.`, `!`, `?` followed by whitespace; min 8 chars per sentence
- System prompt: conversational, no markdown/bullets/special chars, 3-4 sentences max
- Trim conversation history to last 10 turns before each Ollama call
- `_strip_markdown` regex: `^[>#\-\*]+\s*` (NOT `^[\s>#\-\*]+`). The latter
  ate leading whitespace from per-token chunks like `" am"` → `"am"`, collapsing
  streamed output into `"Iamsorry"`. Keep the `\s` out of the character class.

### STT (stt/transcriber.py)
- `WhisperModel("base.en", device="cpu", compute_type="int8")`
- Enable `vad_filter=True` in transcribe call to suppress hallucinations on silence

## Install Sequence (order matters)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch==2.4.0 torchaudio==2.4.0
pip install -e .
local-tts download-models                          # whisper base.en + Kokoro-82M (~400MB)
```

## Dependencies

```toml
"torch==2.4.0", "torchaudio==2.4.0",
"faster-whisper==1.2.1",
"ollama==0.6.2",
"sounddevice==0.5.5",
"numpy>=2.0.0,<3.0.0",
"webrtcvad-wheels==2.0.14",   # prebuilt ARM64 wheels
"click==8.1.8", "rich==15.0.0", "pynput==1.8.1",
"pydantic==2.13.3", "pyyaml>=6.0",
"kokoro>=0.9.4", "misaki[en]>=0.9.4", "soundfile>=0.12.1"
```

## CLI Commands

```
local-tts run [--model MODEL] [--text-mode] [--config path]
local-tts list-devices        # show sounddevice input/output device indices
local-tts list-models         # show Ollama models available on configured host
local-tts download-models     # pre-download whisper + Kokoro models (~400MB)
local-tts test-tts "text"     # synthesize one sentence and play it (smoke test)
```

## Voice options (Kokoro)

Voice name = `{lang}{gender}_{name}`. The first letter MUST match `kokoro.lang_code`.

- American English (`lang_code: "a"`): `af_heart` ★, `af_bella` ★, `af_nicole`, `af_sarah`,
  `af_aoede`, `af_kore`, `af_nova`, `af_sky`, `am_michael`, `am_adam`, `am_echo`, `am_puck`
- British English (`lang_code: "b"`): `bf_emma`, `bf_isabella`, `bf_alice`, `bf_lily`,
  `bm_george`, `bm_lewis`, `bm_daniel`, `bm_fable`
- Other langs: Japanese `j*`, Mandarin `z*`, Spanish `e*`, French `f*`, Hindi `h*`,
  Italian `i*`, Portuguese `p*`

Best naturalness picks: **af_heart**, **af_bella**, **bf_emma**.

## Latency Budget (M5 Pro targets)

| Stage | Estimate |
|---|---|
| VAD silence detection | 700ms |
| Whisper base.en (5s audio) | ~300ms |
| First LLM sentence | ~600-900ms |
| Kokoro synthesis of first sentence | ~300-500ms |
| **Total to first spoken word** | ~2 seconds |

## Verification Checklist

1. `local-tts list-devices` → correct mic and speaker shown
2. `local-tts download-models` → whisper + Kokoro download without error
3. `local-tts test-tts "hello"` → hear synthesized speech in current voice
4. `local-tts run --text-mode` → type "hello", hear spoken response
5. `local-tts run` (voice mode) → speak, see transcription, hear response
6. Mid-response interrupt → speak loudly during AI response, AI stops and re-listens
7. AI does NOT self-interrupt from its own speaker output (RMS gate working)
8. F4 toggle → switch voice ↔ text mode, UI updates

## LLM model picks (latency vs quality)

Voice loop feels real-time when LLM first-token < ~400ms. Smaller is better:

| Model | First-token | Notes |
|---|---|---|
| `qwen3:1.7b` | ~150ms | Surprisingly capable for chit-chat |
| `qwen3:4b` | ~300ms | Best speed/quality balance |
| `llama3.2:3b` | ~250ms | Very natural conversation |
| `gemma3:4b` | ~300ms | Warm/conversational tone |
| `qwen3:8b` (default) | ~700–900ms | Best reasoning, noticeable wait |

Switch at runtime: `local-tts run --model qwen3:4b` (must `ollama pull` first).

## Echo / feedback handling

Acoustic feedback (speaker → mic → "user" speech) is the #1 source of bugs.
- **Best fix:** wear headphones. Eliminates the feedback path entirely.
- **Software mitigation:** the RMS gate in `audio/recorder.py` (see VAD section)
  rejects quiet bleed from speakers. Tune `vad.interrupt_rms_threshold` upward
  (e.g. 0.10) if AI still self-interrupts; tune downward if real interrupts
  don't register.
- **Last resort:** `vad.allow_interrupt: false` disables interrupts entirely.

Whisper hallucinations on near-silence (e.g. "of what you.") are a separate
issue caused by mic picking up faint AI playback during the LISTENING phase
right after SPEAKING ends. `vad_filter=True` in the transcribe call helps.
