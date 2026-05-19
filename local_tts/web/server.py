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
import threading
import time
import uuid
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
from local_tts.stt.transcriber import SUPPORTED_MODELS, Transcriber
from local_tts.tools import ClockTool, ToolRegistry, WebSearchTool
from local_tts.tools.web_search import build_default_provider
from local_tts.tts.synthesizer import (
    SUPPORTED_VOICES,
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
SPEECH_FRAMES_TO_START = 8       # ~240ms of speech to begin
SILENCE_FRAMES_TO_END = 25       # ~750ms of silence to finalize
MIN_UTTERANCE_FRAMES = 12        # ~360ms — drop anything shorter (noise blip)


class PipelineModels:
    """Lazy-loaded singleton for the heavy ML components."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.transcriber: Optional[Transcriber] = None
        self.llm: Optional[LLMClient] = None
        self.synth: Optional[Synthesizer] = None
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        log.info("Loading models...")
        self.transcriber = Transcriber(self.cfg.whisper)
        self.transcriber.load()
        # Build the tool registry up-front so toggling tools.enabled at
        # runtime doesn't have to re-instantiate Ollama-facing state.
        registry = ToolRegistry(self.cfg.tools)
        registry.register(ClockTool())
        registry.register(
            WebSearchTool(build_default_provider(self.cfg.tools.web_search_provider))
        )
        self.llm = LLMClient(self.cfg.ollama, self.cfg.persona, tools=registry)
        self.synth = Synthesizer(self.cfg.kokoro)
        self.synth.load()
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
        self.speech_count = 0
        self.silence_count = 0

        self.muted = False
        self.history: list[dict] = []
        self.pipeline_task: Optional[asyncio.Task] = None
        self.interrupt_event = asyncio.Event()
        self.send_lock = asyncio.Lock()         # serialize ws sends

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
        models_available = await asyncio.to_thread(self.models.llm.list_models)
        tools = self.models.llm.tools
        await self.send_json({
            "type": "config",
            "session_id": self.session_id,
            "voice": self.models.synth.current_voice,
            "voices_available": [
                {"id": v, "label": label} for v, label in SUPPORTED_VOICES
            ],
            "model": self.cfg.ollama.model,
            "models_available": models_available,
            "stt_model": self.models.transcriber.current_model,
            "stt_models_available": list(SUPPORTED_MODELS),
            "speed": self.cfg.kokoro.speed,
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
                    if not self.muted and self.pipeline_task is None:
                        await self._handle_audio(msg["bytes"])
                elif "text" in msg and msg["text"] is not None:
                    await self._handle_control(msg["text"])
                elif msg.get("type") == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        finally:
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
            self._reset_vad()
        elif kind == "unmute":
            self.muted = False
        elif kind == "interrupt":
            self.interrupt_event.set()
        elif kind == "text_input":
            user_text = (payload.get("text") or "").strip()
            if not user_text or self.pipeline_task is not None:
                return
            # Cancel any in-flight VAD-captured utterance and run text pipeline.
            self._reset_vad()
            self.interrupt_event.clear()
            self.pipeline_task = asyncio.create_task(self._run_pipeline(text=user_text))
        elif kind == "set_stt_model":
            await self._handle_stt_swap(payload.get("model"))
        elif kind == "set_voice":
            await self._handle_voice_swap(payload.get("voice"))
        elif kind == "set_speed":
            speed = payload.get("speed")
            if isinstance(speed, (int, float)) and 0.5 <= float(speed) <= 2.0:
                self.cfg.kokoro.speed = float(speed)
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

    async def _handle_stt_swap(self, name: Optional[str]):
        """Hot-swap the Whisper model. Refuses to swap mid-pipeline so an
        in-flight transcribe can't get its model yanked."""
        if not name:
            return
        if name not in SUPPORTED_MODELS:
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
        """Switch the Kokoro voice. Refuses mid-pipeline so an in-flight
        synth can't have its pipeline rebuilt under it."""
        if not name:
            return
        if name not in SUPPORTED_VOICE_NAMES:
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
        if self.models.synth.current_voice == name:
            await self.send_json({
                "type": "voice", "state": "ready", "voice": name,
            })
            return
        await self.send_json({
            "type": "voice", "state": "loading", "voice": name,
        })
        try:
            loaded = await asyncio.to_thread(
                self.models.synth.swap_voice, name,
            )
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
            return

        try:
            is_speech = self.vad.is_speech(frame, VAD_SAMPLE_RATE)
        except Exception:
            return

        if is_speech:
            self.speech_count += 1
            self.silence_count = 0
            if not self.in_speech and self.speech_count >= SPEECH_FRAMES_TO_START:
                self.in_speech = True
                await self.send_phase("listening")
            if self.in_speech:
                self.utterance_frames.append(frame)
        else:
            self.speech_count = 0
            if self.in_speech:
                self.silence_count += 1
                self.utterance_frames.append(frame)
                if self.silence_count >= SILENCE_FRAMES_TO_END:
                    frames = self.utterance_frames
                    self._reset_vad()
                    if len(frames) >= MIN_UTTERANCE_FRAMES:
                        await self._dispatch_utterance(frames)
                    else:
                        await self.send_phase("idle")

    def _reset_vad(self):
        self.utterance_frames = []
        self.in_speech = False
        self.speech_count = 0
        self.silence_count = 0
        # Re-arm the wake-word gate so the next utterance requires a new trigger.
        if self.input_mode == "wake_word":
            self.wake_triggered = False
            if self.wakeword_detector is not None:
                self.wakeword_detector.reset()

    async def _dispatch_utterance(self, frames: list[bytes]):
        """Hand off captured audio to the STT→LLM→TTS pipeline."""
        pcm = b"".join(frames)
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32767.0
        self.interrupt_event.clear()
        self.pipeline_task = asyncio.create_task(self._run_pipeline(audio=audio))

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
            "voice": cfg.kokoro.voice,
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
