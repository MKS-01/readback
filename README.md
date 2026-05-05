# local-tts

A Sesame-like local voice conversation CLI — speak to your local LLM and hear it talk back, all on-device.

Built for Apple Silicon (M-series). No cloud calls, no API keys (other than a one-time HuggingFace login for model downloads).

## Stack

- **LLM**: [Ollama](https://ollama.ai/) (any local model)
- **TTS**: [Sesame CSM-1B](https://github.com/SesameAILabs/csm) — natural, expressive speech
- **STT**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CPU int8 via CTranslate2)
- **Audio**: sounddevice + webrtcvad
- **UI**: rich (CLI)

## Architecture

A 3-thread streaming pipeline that overlaps LLM generation, TTS synthesis, and audio playback so the assistant starts speaking as soon as the first sentence is ready:

```
[recorder]   mic → VAD → utterance → transcription_queue
[pipeline]   transcription_queue → Whisper → Ollama (stream)
             → sentence splitter → CSM TTS → playback_queue
[player]     playback_queue → speaker
```

You can interrupt the assistant by speaking — the recorder detects sustained speech during playback and stops the player.

## Setup

Requirements: macOS on Apple Silicon, Python 3.10–3.12, Ollama running locally.

```bash
# 1. Clone and enter
git clone git@github.com:MKS-01/local-tts.git
cd local-tts

# 2. Python env (uv recommended)
uv venv --python 3.11 .venv
source .venv/bin/activate

# 3. Vendor CSM (it's not pip-installable)
git clone https://github.com/SesameAILabs/csm vendor/csm
uv pip install -r vendor/csm/requirements.txt

# 4. Project deps
uv pip install -e .

# 5. HuggingFace login (one-time)
#    Need a free token from https://huggingface.co/settings/tokens
#    Plus access to https://huggingface.co/meta-llama/Llama-3.2-1B (instant)
huggingface-cli login

# 6. Pre-download model weights (~9GB)
local-tts download-models
```

## Usage

```bash
# Voice mode (default)
local-tts run

# Text mode (type questions, hear responses)
local-tts run --text-mode

# Override Ollama model
local-tts run --model llama3.1:8b

# Useful utilities
local-tts list-devices    # show audio device indices
local-tts list-models     # show Ollama models
local-tts test-tts "hello world"
```

In-app:
- **F4** — toggle voice ↔ text mode
- **Speak during a response** — interrupt the assistant
- **Ctrl+C** — quit

## Configuration

Edit `config.yaml` to change Ollama model, voice prompt, VAD sensitivity, audio devices, and more.

## License

MIT
