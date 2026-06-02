"""FastAPI server exposing the local-tts pipeline over WebSocket.

Protocol:
  client → server (JSON control or binary audio):
    binary frames:    raw Int16 PCM @ 16kHz, mono (incoming mic audio)
    json text frames: {"type": "mute"|"unmute"|"interrupt"|"hello"}

  server → client:
    binary frames:    raw Float32 PCM @ 24kHz, mono (TTS output)
    json text frames: {"type": "phase", "value": "idle|listening|thinking|speaking"}
                      {"type": "transcript", "role": "user|assistant", "text": "..."}
                      {"type": "config", "voice": "...", "model": "..."}
                      {"type": "level", "value": 0.0-1.0}   # incoming mic RMS for orb anim

The browser handles echo cancellation in getUserMedia, so we don't need RMS
gates or PTT — the user just talks.
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import numpy as np
import webrtcvad
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from local_tts.config import Config
from local_tts.llm.client import LLMClient
from local_tts.memory import SessionWriter
from local_tts.stt.transcriber import Transcriber
from local_tts.stt.turn import TurnDetector, TurnDetectorUnavailable
from local_tts.tools import ClockTool, ToolRegistry, WebSearchTool
from local_tts.tools.web_search import build_default_provider
from local_tts.tts.synthesizer import (
    SUPPORTED_VOICE_NAMES,
    Synthesizer,
)
from local_tts.wakeword import WakeWordDetector, WakeWordUnavailable

log = logging.getLogger("local_tts.web")

STATIC_DIR = Path(__file__).parent / "static"
# Vite build output. Present after `cd frontend && npm run build`.
DIST_DIR = STATIC_DIR / "dist"

# Strong refs to fire-and-forget finalize tasks. Without this set, the event
# loop only holds weak refs and the GC can drop a task mid-execution
# (https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task).
# Each task removes itself on completion via add_done_callback.
_finalize_tasks: set[asyncio.Task] = set()


def _on_finalize_done(task: asyncio.Task) -> None:
    _finalize_tasks.discard(task)
    if task.cancelled():
        log.warning("session finalize task was cancelled before completion")
        return
    exc = task.exception()
    if exc is not None:
        log.error("session finalize failed", exc_info=exc)
        return
    result = task.result()
    if result is None:
        log.info("session finalize: no markdown written (empty session or disabled)")
    else:
        log.info("session finalize: wrote %s", result)

# VAD constants — must match webrtcvad's accepted frame sizes.
VAD_SAMPLE_RATE = 16000
FRAME_DURATION_MS = 30
FRAME_SAMPLES = int(VAD_SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 480
FRAME_BYTES = FRAME_SAMPLES * 2  # int16

# Utterance segmentation thresholds (in 30ms frames).
# Onset uses a padded ring buffer with a voiced-ratio trigger (tolerant of
# single-frame dropouts) instead of requiring N *consecutive* speech frames —
# and the ring doubles as PRE-ROLL so the onset audio (first word) isn't lost.
PADDING_FRAMES = 10              # ~300ms ring buffer kept before the trigger
SPEECH_TRIGGER_RATIO = 0.6       # voiced fraction of the ring that starts speech
SILENCE_FRAMES_TO_END = 25       # ~750ms of silence → candidate end-of-turn
MIN_UTTERANCE_FRAMES = 12        # ~360ms — drop anything shorter (noise blip)
# Smart-Turn: once a pause reaches SILENCE_FRAMES_TO_END we ask the model if the
# turn is complete. If it says "not yet", we keep listening and re-ask every
# TURN_RECHECK_FRAMES of continued silence to bound CPU (each call ~7-12ms).
TURN_RECHECK_FRAMES = 10         # ~300ms between Smart-Turn re-checks

# Speaker-bleed guard: the mic stays closed while we're speaking AND for a short
# cooldown after the client confirms playback finished (room reverb tail). If the
# client's `playback_done` is lost, a duration-based fallback reopens the mic
# after roughly the audio length + slack so a dropped message can't wedge it shut.
SPEAKING_COOLDOWN_SEC = 0.3      # extra hold after client-confirmed playback end
PLAYBACK_GUARD_SLACK_SEC = 0.75  # network slack added to the fallback timeout


class PipelineModels:
    """Lazy-loaded singleton for the heavy ML components."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.transcriber: Optional[Transcriber] = None
        self.llm: Optional[LLMClient] = None
        self.synth: Optional[Synthesizer] = None
        # Smart-Turn detector; stays None if disabled or it fails to load
        # (graceful fallback to VAD-only end-of-turn).
        self.turn_detector: Optional[TurnDetector] = None
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        log.info("Loading models...")
        self.transcriber = Transcriber(self.cfg.stt)
        self.transcriber.load()
        if self.cfg.turn.enabled:
            td = TurnDetector(self.cfg.turn)
            try:
                td.load()
                self.turn_detector = td
            except TurnDetectorUnavailable as e:
                log.warning(
                    "Smart-Turn unavailable — falling back to VAD-only "
                    "end-of-turn: %s", e,
                )
        # Build the tool registry up-front so toggling tools.enabled at
        # runtime doesn't have to re-instantiate Ollama-facing state.
        registry = ToolRegistry(self.cfg.tools)
        registry.register(ClockTool())
        registry.register(
            WebSearchTool(build_default_provider(self.cfg.tools.web_search_provider))
        )
        self.llm = LLMClient(self.cfg.ollama, self.cfg.persona, tools=registry)
        self.synth = Synthesizer(self.cfg.tts)
        self.synth.load()
        # If the configured default voice is a clone, resolve its reference
        # transcript now (Whisper, this thread) so the first utterance can synth
        # without a cold transcription stall.
        default_voice = self.synth.current_voice
        if self.synth.is_clone(default_voice) and not self.synth.has_ref_text(default_voice):
            clone = self.synth.clone_for(default_voice)
            if clone is not None:
                try:
                    wav = str(Path(clone.wav).expanduser())
                    if Path(wav).exists():
                        text = self.transcriber.transcribe_clone_ref(wav, clone.ref_lang)
                        if text:
                            self.synth.set_ref_text(clone.name, text)
                            log.info(
                                "default clone %r ref_text resolved (%d chars)",
                                clone.name, len(text),
                            )
                        else:
                            log.warning("default clone %r: empty transcript", clone.name)
                    else:
                        log.warning("default clone %r wav not found: %s", clone.name, wav)
                except Exception:
                    log.exception("failed to resolve default clone ref_text")
        self._loaded = True
        log.info("Models ready.")


class Session:
    """Per-WebSocket connection state. One session = one 'call'."""

    def __init__(self, ws: WebSocket, models: PipelineModels):
        self.ws = ws
        self.models = models
        self.cfg = models.cfg
        # Stable identifier for this WebSocket connection. Plumbed into every
        # transcript payload so the client can correlate turns with a session,
        # and used by SessionWriter (Phase 3) as the file/folder key.
        self.session_id = uuid.uuid4().hex

        self.vad = webrtcvad.Vad(self.cfg.vad.aggressiveness)
        self.audio_buffer = bytearray()         # raw int16 bytes from client
        self.utterance_frames: list[bytes] = []
        self.in_speech = False
        self.silence_count = 0
        # Pre-roll ring of recent (frame, is_speech) pairs kept while NOT yet in
        # speech. On trigger it's flushed into the utterance so the onset (first
        # word) is preserved instead of dropped.
        self._ring: deque[tuple[bytes, bool]] = deque(maxlen=PADDING_FRAMES)
        # Silence-frame count at which to next run Smart-Turn (re-armed each
        # time the model says "not done yet").
        self._next_turn_check = SILENCE_FRAMES_TO_END

        self.muted = False
        self.history: list[dict] = []
        self.pipeline_task: Optional[asyncio.Task] = None
        self.interrupt_event = asyncio.Event()
        self.send_lock = asyncio.Lock()         # serialize ws sends

        # Streaming ASR (Phase 2). When the active engine supports streaming
        # (Parakeet), mic frames are fanned out to a dedicated worker thread
        # that feeds the live transcription stream and emits partial captions.
        # MLX/Metal is not multi-thread safe, so ALL streaming inference runs on
        # this one thread. Whisper has no streaming API and uses the batch path.
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._asr_q: "queue.Queue[tuple[str, Optional[np.ndarray]]]" = queue.Queue()
        self._asr_thread: Optional[threading.Thread] = None
        # True between queuing a finalize and the pipeline actually launching, so
        # late mic frames don't start a phantom new stream in that window.
        self._awaiting_finalize = False

        # Speaker-bleed guard. True while TTS is (or may still be) audible on the
        # client; the mic gate stays closed until the client confirms playback
        # drained (`playback_done`) + a short cooldown, or a duration-based
        # fallback fires. Without this the mic reopens the instant the last chunk
        # is *sent*, while the browser is still *playing* seconds of buffered
        # audio — which bleeds back in and self-triggers a new "utterance".
        self._speaking = False
        self._audio_seconds_sent = 0.0
        self._playback_guard: Optional[asyncio.Task] = None

        # Listening mode + wake-word detector. The detector is created lazily
        # only when the user switches to wake_word mode (avoids onnxruntime
        # import for users who never use this feature).
        self.input_mode: str = self.cfg.input.mode
        self.wake_triggered: bool = False
        self.wakeword_detector: Optional[WakeWordDetector] = None

        # No-op when obsidian.enabled is False; otherwise records turns and
        # writes a markdown transcript at session end.
        self.writer = SessionWriter(
            session_id=self.session_id,
            obsidian=self.cfg.obsidian,
            memory=self.cfg.memory,
        )

    async def run(self):
        self.loop = asyncio.get_running_loop()
        models_available = await asyncio.to_thread(self.models.llm.list_models)
        tools = self.models.llm.tools
        await self.send_json({
            "type": "config",
            "session_id": self.session_id,
            "voice": self.models.synth.current_voice,
            "voices_available": [
                {"id": v, "label": label}
                for v, label in self.models.synth.supported_voices
            ],
            "model": self.cfg.ollama.model,
            "models_available": models_available,
            "stt_engine": self.models.transcriber.current_engine,
            "stt_engines_available": list(self.models.transcriber.engines_available),
            "stt_model": self.models.transcriber.current_model,
            "stt_models_available": list(self.models.transcriber.models_for()),
            "turn_enabled": self.models.turn_detector is not None,
            "speed": self.cfg.tts.qwen.speed,
            "persona": self.models.llm.active_persona.name,
            "personas_available": self.models.llm.list_personas(),
            "tools_enabled": tools.enabled if tools else False,
            "tools_available": tools.names() if tools else [],
            "tools_allowed": list(self.cfg.tools.allowed),
            "input_mode": self.input_mode,
            "wakeword_model": self.cfg.wakeword.model,
            # Cosmetic alias; falls back to the real model name when unset.
            "wakeword_display_name": (
                self.cfg.wakeword.display_name or self.cfg.wakeword.model
            ),
            "obsidian_enabled": self.cfg.obsidian.enabled,
        })
        await self.send_phase("idle")

        # Start session persistence now that we know the active model/voice/persona.
        self.writer.start(
            model=self.cfg.ollama.model,
            voice=self.models.synth.current_voice,
            persona=self.models.llm.active_persona.name,
        )

        try:
            while True:
                msg = await self.ws.receive()
                if "bytes" in msg and msg["bytes"] is not None:
                    if (
                        not self.muted
                        and self.pipeline_task is None
                        and not self._awaiting_finalize
                        and not self._speaking
                    ):
                        await self._handle_audio(msg["bytes"])
                elif "text" in msg and msg["text"] is not None:
                    await self._handle_control(msg["text"])
                elif msg.get("type") == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            self._stop_asr_worker()
            self._cancel_playback_guard()
            if self.pipeline_task and not self.pipeline_task.done():
                self.pipeline_task.cancel()
            # Fire-and-forget: run finalize (which makes a topic LLM call and
            # writes the markdown file) on a background thread so the socket
            # close doesn't block on Ollama latency. Hold a strong reference
            # in _finalize_tasks so the loop's weak ref doesn't let the task
            # get GC'd before the thread finishes.
            try:
                task = asyncio.create_task(
                    asyncio.to_thread(self.writer.finalize, self.models.llm)
                )
                _finalize_tasks.add(task)
                task.add_done_callback(_on_finalize_done)
            except Exception:
                log.exception("could not schedule session finalize")

    async def _handle_control(self, text: str):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return
        kind = payload.get("type")
        if kind == "mute":
            self.muted = True
            self._stop_speaking()
            self._reset_vad()
            self._abort_asr_stream()
        elif kind == "unmute":
            self.muted = False
        elif kind == "interrupt":
            self.interrupt_event.set()
            # Client has stopped playback (stopAllPlayback), so nothing is
            # audible anymore — reopen the mic without the long fallback wait.
            self._stop_speaking()
            self._abort_asr_stream()
        elif kind == "playback_done":
            # Client finished playing the queued TTS. Reopen the mic after a
            # short cooldown to swallow the room-reverb tail.
            self._arm_playback_guard(SPEAKING_COOLDOWN_SEC)
        elif kind == "text_input":
            user_text = (payload.get("text") or "").strip()
            if not user_text or self.pipeline_task is not None:
                return
            # Cancel any in-flight VAD-captured utterance and run text pipeline.
            self._reset_vad()
            self.interrupt_event.clear()
            self.pipeline_task = asyncio.create_task(self._run_pipeline(text=user_text))
        elif kind == "set_stt_engine":
            await self._handle_stt_engine(payload.get("engine"))
        elif kind == "set_stt_model":
            await self._handle_stt_swap(payload.get("model"))
        elif kind == "set_voice":
            await self._handle_voice_swap(payload.get("voice"))
        elif kind == "set_speed":
            speed = payload.get("speed")
            if isinstance(speed, (int, float)) and 0.5 <= float(speed) <= 2.0:
                self.cfg.tts.qwen.speed = float(speed)
        elif kind == "set_model":
            model = (payload.get("model") or "").strip()
            if model and model != self.cfg.ollama.model:
                old_model = self.cfg.ollama.model
                await self.send_json({"type": "model", "state": "unloading", "model": old_model})
                await asyncio.to_thread(self.models.llm.unload_model, old_model)
                self.cfg.ollama.model = model
                await self.send_json({"type": "model", "state": "ready", "model": model})
        elif kind == "set_tools_enabled":
            value = bool(payload.get("value"))
            self.cfg.tools.enabled = value
            await self.send_json({"type": "tools_enabled", "value": value})
        elif kind == "set_tool_allowed":
            tool = (payload.get("tool") or "").strip()
            value = bool(payload.get("value"))
            if tool:
                allowed = list(self.cfg.tools.allowed)
                if value and tool not in allowed:
                    allowed.append(tool)
                elif not value and tool in allowed:
                    allowed = [t for t in allowed if t != tool]
                self.cfg.tools.allowed = allowed
                await self.send_json({
                    "type": "tools_allowed",
                    "value": allowed,
                })
        elif kind == "set_persona":
            await self._handle_persona_swap(payload.get("name"))
        elif kind == "set_persona_custom_prompt":
            prompt = (payload.get("prompt") or "").strip()
            if prompt:
                self.models.llm.set_custom_prompt(prompt)
                await self.send_json({
                    "type": "persona",
                    "state": "ready",
                    "name": "custom",
                    "personas_available": self.models.llm.list_personas(),
                })
        elif kind == "set_input_mode":
            await self._handle_input_mode(payload.get("mode"))

    async def _handle_stt_engine(self, engine: Optional[str]):
        """Switch the active ASR engine (parakeet <-> whisper) and report the
        new engine's model list. Refuses mid-pipeline like the model swap."""
        if not engine:
            return
        transcriber = self.models.transcriber
        if engine not in transcriber.engines_available:
            await self.send_json({
                "type": "stt_engine",
                "state": "error",
                "engine": engine,
                "message": f"Unsupported engine {engine!r}",
            })
            return
        if self.pipeline_task and not self.pipeline_task.done():
            await self.send_json({
                "type": "stt_engine",
                "state": "error",
                "engine": engine,
                "message": "Wait for the current response to finish, then try again.",
            })
            return
        if transcriber.current_engine == engine:
            await self.send_json({
                "type": "stt_engine", "state": "ready", "engine": engine,
                "model": transcriber.current_model,
                "models_available": list(transcriber.models_for(engine)),
            })
            return
        await self.send_json({
            "type": "stt_engine", "state": "loading", "engine": engine,
        })
        try:
            loaded = await asyncio.to_thread(transcriber.swap_engine, engine)
            await self.send_json({
                "type": "stt_engine",
                "state": "ready",
                "engine": loaded,
                "model": transcriber.current_model,
                "models_available": list(transcriber.models_for(loaded)),
            })
        except Exception as e:
            log.exception("stt engine swap failed")
            await self.send_json({
                "type": "stt_engine",
                "state": "error",
                "engine": engine,
                "message": str(e),
            })

    async def _handle_stt_swap(self, name: Optional[str]):
        """Hot-swap the active ASR engine's model. Refuses to swap mid-pipeline
        so an in-flight transcribe can't get its model yanked."""
        if not name:
            return
        if name not in self.models.transcriber.models_for():
            await self.send_json({
                "type": "stt_model",
                "state": "error",
                "model": name,
                "message": f"Unsupported model {name!r}",
            })
            return
        if self.pipeline_task and not self.pipeline_task.done():
            await self.send_json({
                "type": "stt_model",
                "state": "error",
                "model": name,
                "message": "Wait for the current response to finish, then try again.",
            })
            return
        if self.models.transcriber.current_model == name:
            await self.send_json({
                "type": "stt_model", "state": "ready", "model": name,
            })
            return
        await self.send_json({
            "type": "stt_model", "state": "loading", "model": name,
        })
        try:
            loaded = await asyncio.to_thread(
                self.models.transcriber.swap_model, name,
            )
            await self.send_json({
                "type": "stt_model", "state": "ready", "model": loaded,
            })
        except Exception as e:
            log.exception("stt swap failed")
            await self.send_json({
                "type": "stt_model",
                "state": "error",
                "model": name,
                "message": str(e),
            })

    async def _handle_persona_swap(self, name: Optional[str]):
        """Switch the active persona. Refuses mid-pipeline so an in-flight
        response can't have its system prompt yanked between sentences."""
        if not name:
            return
        if self.pipeline_task and not self.pipeline_task.done():
            await self.send_json({
                "type": "persona",
                "state": "error",
                "name": name,
                "message": "Wait for the current response to finish, then try again.",
            })
            return
        try:
            loaded = await asyncio.to_thread(self.models.llm.swap_persona, name)
            await self.send_json({
                "type": "persona",
                "state": "ready",
                "name": loaded,
            })
        except Exception as e:
            await self.send_json({
                "type": "persona",
                "state": "error",
                "name": name,
                "message": str(e),
            })

    async def _handle_input_mode(self, mode: Optional[str]):
        """Switch between VAD and wake-word listening. On wake_word selection
        the detector is loaded synchronously; failure (e.g. openwakeword not
        installed) reports back as an error and leaves the mode unchanged."""
        if mode not in ("vad", "wake_word"):
            return
        if mode == self.input_mode:
            await self.send_json({"type": "input_mode", "value": mode})
            return
        if mode == "wake_word":
            if self.wakeword_detector is None:
                self.wakeword_detector = WakeWordDetector(
                    model=self.cfg.wakeword.model,
                    threshold=self.cfg.wakeword.threshold,
                )
            try:
                await asyncio.to_thread(self.wakeword_detector.load)
            except WakeWordUnavailable as e:
                await self.send_json({
                    "type": "input_mode",
                    "state": "error",
                    "value": "vad",
                    "message": str(e),
                })
                self.wakeword_detector = None
                return
        self.input_mode = mode
        self.cfg.input.mode = mode
        self.wake_triggered = False
        self._reset_vad()
        await self.send_json({"type": "input_mode", "value": mode})

    async def _handle_voice_swap(self, name: Optional[str]):
        """Switch the active TTS voice. Refuses mid-pipeline so an in-flight
        synth can't have its model swapped under it. Presets switch instantly;
        a clone ("clone:<name>") triggers a Base-model reload and, on first use,
        resolves the reference transcript via Whisper before swapping."""
        if not name:
            return
        synth = self.models.synth
        is_clone = synth.is_clone(name)
        if is_clone:
            clone = synth.clone_for(name)
            if clone is None:
                await self.send_json({
                    "type": "voice", "state": "error", "voice": name,
                    "message": f"Unknown cloned voice {name!r}",
                })
                return
        elif name not in SUPPORTED_VOICE_NAMES:
            await self.send_json({
                "type": "voice",
                "state": "error",
                "voice": name,
                "message": f"Unsupported voice {name!r}",
            })
            return
        if self.pipeline_task and not self.pipeline_task.done():
            await self.send_json({
                "type": "voice",
                "state": "error",
                "voice": name,
                "message": "Wait for the current response to finish, then try again.",
            })
            return
        if synth.current_voice == name:
            await self.send_json({
                "type": "voice", "state": "ready", "voice": name,
            })
            return
        await self.send_json({
            "type": "voice", "state": "loading", "voice": name,
        })
        try:
            # Resolve the clone's reference transcript first (Whisper, off the
            # MLX/TTS thread) so the executor never blocks on transcription.
            if is_clone and not synth.has_ref_text(name):
                wav = str(Path(clone.wav).expanduser())
                if not Path(wav).exists():
                    raise FileNotFoundError(f"reference wav not found: {wav}")
                text = await asyncio.to_thread(
                    self.models.transcriber.transcribe_clone_ref,
                    wav, clone.ref_lang,
                )
                if not text:
                    raise RuntimeError("reference clip produced an empty transcript")
                synth.set_ref_text(clone.name, text)
                log.info("clone %r ref_text resolved (%d chars)", clone.name, len(text))
            loaded = await asyncio.to_thread(synth.swap_voice, name)
            await self.send_json({
                "type": "voice", "state": "ready", "voice": loaded,
            })
        except Exception as e:
            log.exception("voice swap failed")
            await self.send_json({
                "type": "voice",
                "state": "error",
                "voice": name,
                "message": str(e),
            })

    async def _handle_audio(self, data: bytes):
        """Append incoming Int16 PCM, slice into VAD frames, segment utterances."""
        self.audio_buffer.extend(data)
        # Emit a coarse mic level for the orb (one per chunk arrival).
        if data:
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32767.0
            level = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
            await self.send_json({"type": "level", "value": level})

        while len(self.audio_buffer) >= FRAME_BYTES:
            frame = bytes(self.audio_buffer[:FRAME_BYTES])
            del self.audio_buffer[:FRAME_BYTES]
            await self._process_frame(frame)

    async def _process_frame(self, frame: bytes):
        # Wake-word gate: in wake_word mode, audio is ignored until the
        # configured word fires. Once triggered, fall through to VAD so the
        # utterance boundary is still detected normally.
        if self.input_mode == "wake_word" and not self.wake_triggered:
            if self.wakeword_detector is None:
                return
            try:
                hit = self.wakeword_detector.process_int16(frame)
            except Exception:
                log.exception("wakeword detector error")
                return
            if not hit:
                return
            self.wake_triggered = True
            await self.send_phase("listening")
            self.in_speech = True
            self.utterance_frames.append(frame)
            if self.models.transcriber.supports_streaming:
                self._feed_asr(frame)
            return

        try:
            is_speech = self.vad.is_speech(frame, VAD_SAMPLE_RATE)
        except Exception:
            return

        streaming = self.models.transcriber.supports_streaming

        if not self.in_speech:
            # Pre-trigger: buffer recent frames; start when enough of the ring
            # is voiced (tolerant of single-frame dropouts in the onset).
            self._ring.append((frame, is_speech))
            voiced = sum(1 for _, s in self._ring if s)
            if voiced >= SPEECH_TRIGGER_RATIO * self._ring.maxlen:
                self.in_speech = True
                self.silence_count = 0
                self._next_turn_check = SILENCE_FRAMES_TO_END
                log.info("speech start (ring voiced=%d/%d)", voiced, self._ring.maxlen)
                await self.send_phase("listening")
                # Flush the ring as pre-roll so the onset audio is captured.
                for f, _ in self._ring:
                    self.utterance_frames.append(f)
                    if streaming:
                        self._feed_asr(f)
                self._ring.clear()
            return

        # In speech: every frame is part of the utterance.
        self.utterance_frames.append(frame)
        if streaming:
            self._feed_asr(frame)
        if is_speech:
            self.silence_count = 0
            self._next_turn_check = SILENCE_FRAMES_TO_END
        else:
            self.silence_count += 1
            if self.silence_count >= SILENCE_FRAMES_TO_END:
                # webrtcvad pause reached — let Smart-Turn confirm it's a real
                # end-of-turn (else keep listening through the pause).
                if await self._turn_is_complete():
                    await self._end_utterance(streaming)

    # ---- speaker-bleed guard -------------------------------------------------

    def _begin_speaking(self):
        """Close the mic gate for the duration of a spoken response."""
        self._speaking = True
        self._audio_seconds_sent = 0.0
        self._cancel_playback_guard()

    def _stop_speaking(self):
        """Reopen the mic immediately (interrupt/mute — nothing is audible)."""
        self._speaking = False
        self._cancel_playback_guard()

    def _cancel_playback_guard(self):
        if self._playback_guard is not None and not self._playback_guard.done():
            self._playback_guard.cancel()
        self._playback_guard = None

    def _arm_playback_guard(self, delay: float):
        """Reopen the mic `delay` seconds from now, replacing any pending guard.

        Used both as the post-playback cooldown (on client `playback_done`) and
        as the duration-based fallback armed when the last TTS chunk is sent, so
        a lost `playback_done` can't leave the mic shut forever.
        """
        if not self._speaking:
            return
        self._cancel_playback_guard()

        async def _guard():
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            self._speaking = False
            self._reset_vad()

        self._playback_guard = asyncio.create_task(_guard())

    def _reset_vad(self):
        self.utterance_frames = []
        self.in_speech = False
        self.silence_count = 0
        self._ring.clear()
        self._next_turn_check = SILENCE_FRAMES_TO_END
        # Re-arm the wake-word gate so the next utterance requires a new trigger.
        if self.input_mode == "wake_word":
            self.wake_triggered = False
            if self.wakeword_detector is not None:
                self.wakeword_detector.reset()

    async def _dispatch_utterance(self, frames: list[bytes]):
        """Hand off captured audio to the STT→LLM→TTS pipeline (batch engines)."""
        pcm = b"".join(frames)
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32767.0
        self.interrupt_event.clear()
        self.pipeline_task = asyncio.create_task(self._run_pipeline(audio=audio))

    # ---- turn detection (Smart-Turn v3) ----

    def _utterance_audio(self) -> np.ndarray:
        pcm = b"".join(self.utterance_frames)
        return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32767.0

    async def _turn_is_complete(self) -> bool:
        """Decide whether the current pause is a real end-of-turn. Returns True
        for plain VAD behavior when Smart-Turn is unavailable."""
        td = self.models.turn_detector
        if td is None:
            return True  # VAD-only: a long-enough pause ends the turn
        # Safety cap: don't wait forever on a trailing pause.
        max_wait_frames = int(self.cfg.turn.max_wait_sec * 1000 / FRAME_DURATION_MS)
        if self.silence_count >= max_wait_frames:
            return True
        # Throttle: only re-run the model every TURN_RECHECK_FRAMES.
        if self.silence_count < self._next_turn_check:
            return False
        self._next_turn_check = self.silence_count + TURN_RECHECK_FRAMES
        try:
            prob = await asyncio.to_thread(
                td.probability, self._utterance_audio(), VAD_SAMPLE_RATE,
            )
        except Exception:
            log.exception("smart-turn inference failed; finalizing on VAD")
            return True  # fail open — better to end the turn than hang
        complete = prob >= self.cfg.turn.threshold
        log.info("smart-turn p=%.2f complete=%s (silence=%d)", prob, complete, self.silence_count)
        if not complete:
            # Tell the UI we're still waiting through a mid-thought pause.
            await self.send_json({"type": "turn", "state": "waiting", "prob": prob})
        return complete

    async def _end_utterance(self, streaming: bool):
        """Finalize the current utterance (Smart-Turn confirmed end-of-turn)."""
        frames = self.utterance_frames
        long_enough = len(frames) >= MIN_UTTERANCE_FRAMES
        log.info(
            "utterance end: %d frames (%.1fs)%s",
            len(frames), len(frames) * FRAME_DURATION_MS / 1000,
            "" if long_enough else " — too short, dropped",
        )
        self._reset_vad()
        if streaming:
            # The worker thread owns the transcript: it finalizes the live
            # stream (or batch-falls-back) and launches the pipeline with the
            # resulting text. Block late frames until that launch lands.
            if long_enough:
                self._awaiting_finalize = True
                self._asr_q.put(("finalize", None))
            else:
                self._asr_q.put(("abort", None))
                await self.send_phase("idle")
        else:
            if long_enough:
                await self._dispatch_utterance(frames)
            else:
                await self.send_phase("idle")

    # ---- streaming ASR worker (Parakeet) ----

    def _feed_asr(self, frame: bytes):
        """Queue one mic frame for the streaming ASR worker (float32 [-1, 1])."""
        self._ensure_asr_worker()
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32767.0
        self._asr_q.put(("audio", samples))

    def _ensure_asr_worker(self):
        if self._asr_thread is not None and self._asr_thread.is_alive():
            return
        self._asr_thread = threading.Thread(
            target=self._asr_worker_loop, name=f"asr-{self.session_id[:6]}", daemon=True,
        )
        self._asr_thread.start()

    def _asr_worker_loop(self):
        """Single thread that owns the Parakeet streaming context (MLX is not
        multi-thread safe). Consumes audio frames, emits partial captions, and
        on finalize hands the transcript back to the event loop."""
        engine = None
        pending: list[np.ndarray] = []
        while True:
            cmd, payload = self._asr_q.get()
            if cmd == "stop":
                if engine is not None:
                    engine.abort_stream()
                return
            if cmd == "audio":
                if engine is None:
                    engine = self.models.transcriber.streaming_engine()
                    if engine is None:
                        continue
                    try:
                        engine.start_stream()
                    except Exception:
                        log.exception("asr stream start failed")
                        engine = None
                        continue
                    pending = []
                pending.append(payload)
                try:
                    partial = engine.feed(payload, VAD_SAMPLE_RATE)
                except Exception:
                    log.exception("asr feed failed")
                    continue
                if partial:
                    self._emit_threadsafe({
                        "type": "partial",
                        "text": partial,
                        "session_id": self.session_id,
                    })
            elif cmd == "abort":
                if engine is not None:
                    engine.abort_stream()
                    engine = None
                pending = []
            elif cmd == "finalize":
                # The live stream was only for partial captions; commit an
                # accurate BATCH transcription of the full buffered utterance
                # (streaming decode is lossier on real, noisy mic audio).
                streamed = ""
                if engine is not None:
                    try:
                        streamed = engine.partial_text
                    except Exception:
                        pass
                    try:
                        engine.abort_stream()
                    except Exception:
                        log.exception("asr stream close failed")
                    engine = None
                text = ""
                if pending:
                    try:
                        audio = np.concatenate(pending)
                        text = self.models.transcriber.transcribe(audio, VAD_SAMPLE_RATE)
                    except Exception:
                        log.exception("asr batch transcribe failed")
                if not text:
                    text = streamed  # last resort if batch returned nothing
                dur = sum(len(p) for p in pending) / VAD_SAMPLE_RATE
                log.info(
                    "ASR final: %r  (%.1fs audio; streamed partial=%r)",
                    text, dur, streamed,
                )
                pending = []
                self._launch_pipeline_threadsafe(text)

    def _emit_threadsafe(self, payload: dict):
        """Schedule a ws send from the worker thread onto the event loop."""
        loop = self.loop
        if loop is None:
            return
        loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self.send_json(payload))
        )

    def _launch_pipeline_threadsafe(self, text: str):
        loop = self.loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._launch_pipeline_from_stream, text)

    def _launch_pipeline_from_stream(self, text: str):
        """Runs on the event-loop thread. Starts the pipeline with the finalized
        streaming transcript (skips re-running STT)."""
        self._awaiting_finalize = False
        text = (text or "").strip()
        if not text or self.pipeline_task is not None:
            asyncio.ensure_future(self.send_phase("idle"))
            return
        self.interrupt_event.clear()
        self.pipeline_task = asyncio.create_task(self._run_pipeline(text=text))

    def _abort_asr_stream(self):
        self._awaiting_finalize = False
        if self._asr_thread is not None and self._asr_thread.is_alive():
            self._asr_q.put(("abort", None))

    def _stop_asr_worker(self):
        if self._asr_thread is not None and self._asr_thread.is_alive():
            self._asr_q.put(("stop", None))

    async def _run_pipeline(self, *, audio: Optional[np.ndarray] = None, text: Optional[str] = None):
        try:
            if text is None:
                # Voice path: STT first
                await self.send_phase("thinking")
                user_text = await asyncio.to_thread(
                    self.models.transcriber.transcribe, audio, VAD_SAMPLE_RATE
                )
                user_text = (user_text or "").strip()
            else:
                # Text path: skip STT
                user_text = text.strip()

            if not user_text:
                await self.send_phase("idle")
                return
            await self.send_json({
                "type": "transcript",
                "role": "user",
                "text": user_text,
                "session_id": self.session_id,
            })
            await self.send_phase("thinking")

            self.history.append({"role": "user", "content": user_text})
            self.history = self.history[-self.cfg.ui.history_turns * 2:]
            self.writer.append_turn("user", user_text, time.time())

            self._begin_speaking()
            await self.send_phase("speaking")
            full_response: list[str] = []

            # Stream sentences from Ollama in a producer thread and consume
            # them here so we can race each step against `interrupt_event`.
            # Without this, Skip would have to wait for the full LLM response
            # to materialize before having any effect.
            sentence_q: asyncio.Queue = asyncio.Queue()
            SENTINEL = object()
            stop_event = threading.Event()
            loop = asyncio.get_running_loop()

            def _producer():
                try:
                    for sentence in self.models.llm.stream_response(
                        self.history, stop_event=stop_event,
                    ):
                        if stop_event.is_set():
                            break
                        loop.call_soon_threadsafe(sentence_q.put_nowait, sentence)
                except Exception:
                    log.exception("llm producer error")
                finally:
                    loop.call_soon_threadsafe(sentence_q.put_nowait, SENTINEL)

            producer_task = asyncio.create_task(asyncio.to_thread(_producer))

            try:
                while True:
                    sentence = await self._race_with_interrupt(sentence_q.get())
                    if sentence is None:           # interrupted
                        stop_event.set()
                        break
                    if sentence is SENTINEL:       # producer drained
                        break
                    full_response.append(sentence)
                    await self.send_json({
                        "type": "transcript",
                        "role": "assistant",
                        "text": sentence,
                        "session_id": self.session_id,
                    })
                    # Synthesize the whole sentence, then send it as one buffer.
                    # NOTE: per-chunk model streaming (synthesize_stream) was tried
                    # (Phase 7) and reverted — see "TTS — Qwen3-TTS". It cuts
                    # first-audio latency on fast engines, but on a slow engine
                    # (the cloned Base model, RTF near realtime) each small chunk
                    # must arrive in realtime; when it can't, the client queue
                    # underruns *mid-sentence* and chops. Batching one sentence at
                    # a time keeps playback gapless within a sentence regardless of
                    # synth speed; the client jitter buffer (audioEngine LEAD_SEC)
                    # absorbs the between-sentence stall.
                    audio_arr = await self._race_with_interrupt(
                        asyncio.to_thread(self.models.synth.synthesize, sentence)
                    )
                    if audio_arr is None:          # interrupted mid-synth
                        stop_event.set()
                        break
                    if audio_arr.size > 0:
                        await self.send_audio(audio_arr)
            finally:
                stop_event.set()
                # Producer thread will exit on its own next chunk-check; don't
                # await it here so a slow Ollama close can't stall us.
                if not producer_task.done():
                    producer_task.add_done_callback(lambda _t: None)
                # Keep the mic closed until the client confirms playback drained
                # (`playback_done`). Arm a duration-based fallback in case that
                # message is lost: ~audio length still queued + cooldown + slack.
                if self.interrupt_event.is_set():
                    self._stop_speaking()
                elif self._speaking:
                    self._arm_playback_guard(
                        self._audio_seconds_sent
                        + SPEAKING_COOLDOWN_SEC
                        + PLAYBACK_GUARD_SLACK_SEC
                    )

            if full_response and not self.interrupt_event.is_set():
                final_text = " ".join(full_response)
                self.history.append({
                    "role": "assistant", "content": final_text,
                })
                self.writer.append_turn("assistant", final_text, time.time())
            await self.send_phase("idle")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.exception("pipeline error")
            await self.send_json({"type": "error", "message": str(e)})
            await self.send_phase("idle")
        finally:
            self.pipeline_task = None

    async def _race_with_interrupt(self, awaitable):
        """Await `awaitable` but bail out the moment `interrupt_event` is set.

        Returns the awaited value on success, or None if the interrupt fired
        first. The losing task is cancelled so we don't leak it.
        """
        if self.interrupt_event.is_set():
            # awaitable might be a raw coroutine (e.g. sentence_q.get()); close
            # it so Python doesn't emit "coroutine was never awaited" warnings.
            if hasattr(awaitable, "close"):
                try:
                    awaitable.close()
                except Exception:
                    pass
            return None
        target = asyncio.ensure_future(awaitable)
        intr = asyncio.ensure_future(self.interrupt_event.wait())
        try:
            done, pending = await asyncio.wait(
                {target, intr}, return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for t in (target, intr):
                if not t.done():
                    t.cancel()
        if intr in done:
            # Surface and swallow any exception target may have raised
            # post-cancel, so it doesn't show up as "Task exception was never retrieved".
            try:
                await target
            except (asyncio.CancelledError, Exception):
                pass
            return None
        return target.result()

    # ---- ws send helpers (serialized via lock) ----

    async def send_json(self, payload: dict):
        async with self.send_lock:
            try:
                await self.ws.send_text(json.dumps(payload))
            except Exception:
                pass

    async def send_audio(self, audio: np.ndarray):
        # Float32 PCM @ 24kHz, mono. Browser receives as ArrayBuffer.
        sr = self.models.synth.sample_rate if self.models.synth else 24000
        self._audio_seconds_sent += audio.size / float(sr)
        buf = audio.astype(np.float32).tobytes()
        async with self.send_lock:
            try:
                await self.ws.send_bytes(buf)
            except Exception:
                pass

    async def send_phase(self, phase: str):
        await self.send_json({"type": "phase", "value": phase})


def create_app(cfg: Optional[Config] = None, cert_path: Optional[Path] = None) -> FastAPI:
    cfg = cfg or Config.load()
    models = PipelineModels(cfg)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await asyncio.to_thread(models.load)
        yield

    app = FastAPI(lifespan=lifespan)

    # Force the browser to always revalidate the UI assets — otherwise stale
    # CSS/JS from a prior dev session silently overrides any updates.
    @app.middleware("http")
    async def _no_cache_static(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        # Prefer the React build; fall back to the legacy bundle if the user
        # hasn't run `npm run build` yet (still useful for first-time setup).
        dist_index = DIST_DIR / "index.html"
        if dist_index.exists():
            return FileResponse(str(dist_index))
        return FileResponse(str(STATIC_DIR / "index.html"))

    if cert_path is not None:
        @app.get("/cert.pem")
        async def download_cert():
            return FileResponse(
                str(cert_path),
                media_type="application/x-pem-file",
                headers={"Content-Disposition": "attachment; filename=local-tts.pem"},
            )

    @app.get("/api/config")
    async def get_config():
        return {
            "voice": cfg.tts.qwen.speaker,
            "model": cfg.ollama.model,
            "input_sample_rate": VAD_SAMPLE_RATE,
            "output_sample_rate": models.synth.sample_rate if models.synth else 24000,
        }

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        session = Session(websocket, models)
        await session.run()

    return app
