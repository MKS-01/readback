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
from local_tts.stt.transcriber import SUPPORTED_MODELS, Transcriber
from local_tts.tts.synthesizer import Synthesizer

log = logging.getLogger("local_tts.web")

STATIC_DIR = Path(__file__).parent / "static"

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
        self.llm = LLMClient(self.cfg.ollama)
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

    async def run(self):
        await self.send_json({
            "type": "config",
            "voice": self.cfg.kokoro.voice,
            "model": self.cfg.ollama.model,
            "stt_model": self.models.transcriber.current_model,
            "stt_models_available": list(SUPPORTED_MODELS),
        })
        await self.send_phase("idle")

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
            await self.send_json({"type": "transcript", "role": "user", "text": user_text})
            await self.send_phase("thinking")

            self.history.append({"role": "user", "content": user_text})
            self.history = self.history[-self.cfg.ui.history_turns * 2:]

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
                        "type": "transcript", "role": "assistant", "text": sentence,
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
                self.history.append({
                    "role": "assistant", "content": " ".join(full_response),
                })
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


def create_app(cfg: Optional[Config] = None) -> FastAPI:
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
        return FileResponse(str(STATIC_DIR / "index.html"))

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
