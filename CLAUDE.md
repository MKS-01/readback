# local-tts — Project Context

A local voice conversation app similar to sesame.com, running entirely on-device.
Full voice loop: speak → STT → Ollama LLM → TTS → hear response.
Also supports text-in with voice-out mode.

## Hardware
- Apple M5 Pro, 48GB unified memory
- No CUDA. Use MPS (Metal) for PyTorch models.

## Stack
- **LLM**: Ollama (already running locally, default model: `qwen3:8b`)
- **TTS**: Sesame CSM-1B (`sesame/csm-1b`) — very natural, emotional speech
- **STT**: faster-whisper (`base.en`, CPU int8 mode, CTranslate2 ARM NEON)
- **Audio I/O**: sounddevice + webrtcvad-wheels
- **CLI/UI**: click + rich

## Architecture: 3-Thread Streaming Pipeline

```
[Thread 1: recorder]    mic → VAD → utterance → transcription_queue
[Thread 2: pipeline]    transcription_queue → Whisper → Ollama streaming
                        → sentence splitter → CSM TTS → playback_queue
[Thread 3: player]      playback_queue → sounddevice output

Text mode:              terminal input → pipeline_thread (skips recorder/Whisper)
Interrupt:              recorder detects 300ms sustained speech during SPEAKING
                        → sets interrupt_event → player drains queue and stops
```

## Project Structure

```
local-tts/
├── pyproject.toml
├── config.yaml                  # user-editable defaults
├── vendor/csm/                  # cloned SesameAILabs/csm (not pip-installable)
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
    ├── tts/synthesizer.py       # CSM wrapper, MPS device, context window management
    └── ui/display.py            # rich Live: conversation history + phase status
```

## Critical Implementation Notes

### Apple Silicon / MPS setup (tts/synthesizer.py)
- Set `os.environ["NO_TORCH_COMPILE"] = "1"` BEFORE any torch import (avoids Triton crash)
- Set `PYTORCH_ENABLE_MPS_FALLBACK=1` for transparent CPU fallback on unsupported MPS ops
- Device: `"mps"` when `torch.backends.mps.is_available()`, else `"cpu"`
- After loading model: `model.to(device="mps", dtype=torch.bfloat16)` (sidesteps float64 issue)
- CSM repo lives in `vendor/csm/`; add to `sys.path` at startup for its internal imports

### VAD + Interrupt (audio/recorder.py)
- 16kHz, blocksize=480 (30ms frames — matches webrtcvad requirement)
- 10 speech frames → SPEECH; 23 silence frames (~700ms) → finalize utterance
- If `state.phase == SPEAKING` and 15 consecutive speech frames detected → set `interrupt_event`

### Sentence streaming (llm/client.py)
- Split on `.`, `!`, `?` followed by whitespace; min 10 chars per sentence
- System prompt: conversational, no markdown/bullets/special chars, 3-4 sentences max
- Trim conversation history to last 10 turns before each Ollama call

### STT (stt/transcriber.py)
- `WhisperModel("base.en", device="cpu", compute_type="int8")`
- Enable `vad_filter=True` in transcribe call to suppress hallucinations on silence

### CSM context window (tts/synthesizer.py)
- Keep rolling List[Segment] of last 3-4 turns, prune when estimated tokens > 1500
- Seed with `conversational_a` voice prompt (index 0) for session voice consistency

## Install Sequence (order matters)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch==2.4.0 torchaudio==2.4.0       # MPS-enabled build
git clone https://github.com/SesameAILabs/csm vendor/csm
pip install -r vendor/csm/requirements.txt
pip install -e .
huggingface-cli login                              # need Llama-3.2-1B tokenizer access
local-tts download-models                          # whisper base.en + CSM-1B (~6.2GB)
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
"pydantic==2.13.3", "pyyaml>=6.0"
```

## CLI Commands

```
local-tts run [--model qwen3:8b] [--text-mode] [--config path]
local-tts list-devices        # show sounddevice input/output device indices
local-tts download-models     # pre-download whisper + CSM models
```

## Latency Budget (M5 Pro targets)

| Stage | Estimate |
|---|---|
| VAD silence detection | 700ms |
| Whisper base.en (5s audio) | ~300ms |
| First LLM sentence | ~600-900ms |
| CSM synthesis of first sentence | ~1.5-2.5s |
| **Total to first spoken word** | ~3-4 seconds |

## Verification Checklist

1. `local-tts list-devices` → correct mic and speaker shown
2. `local-tts download-models` → whisper + CSM-1B download without error
3. `local-tts run --text-mode` → type "hello", hear spoken response
4. `local-tts run` (voice mode) → speak, see transcription, hear response
5. Mid-response interrupt → speak during AI response, AI stops and re-listens
6. F4 toggle → switch voice ↔ text mode, UI updates
7. Multi-turn conversation → voice stays consistent (CSM context working)
