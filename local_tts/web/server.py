"""FastAPI server for the offline article reader.

Pivot (v0.8.0): the real-time voice-assistant cascade (STT / VAD / Smart-Turn /
mic / echo gate) is gone. The server now does one job — turn a URL into audio:

    URL → fetch + extract article → (optional LLM summary) → CSM TTS (offline)
        → write WAV → serve it for in-browser playback + download

Synthesis is offline, so there is no real-time constraint (the whole reason for
the pivot): we synthesize the entire piece, then play. Progress streams over a
WebSocket; the finished WAV is served from `cfg.reader.output_dir`.

WS protocol (/ws):
  client → {"type":"read", "url": str, "mode": "full"|"summary", "voice"?: str}
           {"type":"cancel"}   # abort the in-flight read job (stops synthesis)
  server → {"type":"phase",    "value":"loading"|"fetching"|"summarizing"|"synthesizing"}
           {"type":"progress", "done": int, "total": int}
           {"type":"done", "title","audio_url","duration_sec","word_count","mode",
                           "text": str|None (summary text for transcript; None in full mode)}
           {"type":"error", "message": str}
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from local_tts.config import Config
from local_tts.llm.client import LLMClient
from local_tts.reader import ExtractError, fetch_article
from local_tts.reader.speak import synthesize_article, write_wav
from local_tts.reader.summarize import summarize_article
from local_tts.tts.csm_engine import voices_for
from local_tts.tts.synthesizer import Synthesizer

log = logging.getLogger("local_tts.server")

STATIC_DIR = Path(__file__).parent / "static"
DIST_DIR = STATIC_DIR / "dist"


class ReaderModels:
    """Lazily-loaded shared models (one CSM engine + one LLM client). The CSM
    engine serializes all synthesis on its own single MLX thread, so concurrent
    read jobs queue naturally."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.synth: Optional[Synthesizer] = None
        self.llm: Optional[LLMClient] = None
        self._loaded = False
        self._lock = asyncio.Lock()

    def _load_blocking(self):
        if self._loaded:
            return
        self.llm = LLMClient(self.cfg.ollama)
        self.synth = Synthesizer(self.cfg.tts)
        self.synth.load()
        self._loaded = True
        log.info("reader models ready")

    async def ensure_loaded(self):
        if self._loaded:
            return
        async with self._lock:
            if not self._loaded:
                await asyncio.to_thread(self._load_blocking)


async def _run_read_job(
    ws: WebSocket, models: ReaderModels, cfg: Config, payload: dict,
    state: Optional[dict] = None,
) -> None:
    loop = asyncio.get_running_loop()
    # `alive` flips false the moment a send fails (client closed the tab) OR the
    # client sends a `cancel`. It both silences the send path and (via
    # should_stop) aborts synthesis so we don't keep burning GPU on audio nobody
    # will hear. The caller may pass its own state dict so it can flip `alive`.
    if state is None:
        state = {"alive": True}

    async def send(msg: dict):
        if not state["alive"]:
            return
        try:
            await ws.send_json(msg)
        except Exception:
            state["alive"] = False   # disconnected — stop trying

    url = (payload.get("url") or "").strip()
    mode = payload.get("mode") if payload.get("mode") in ("full", "summary") else "full"
    voice = (payload.get("voice") or "").strip()
    if not url:
        await send({"type": "error", "message": "Please enter a URL."})
        return

    # Load models on first use (downloads the CSM checkpoint the very first time).
    if not models._loaded:
        await send({"type": "phase", "value": "loading"})
    await models.ensure_loaded()
    synth, llm = models.synth, models.llm
    assert synth is not None and llm is not None

    # 1) Fetch + extract.
    await send({"type": "phase", "value": "fetching"})
    try:
        article = await asyncio.to_thread(fetch_article, url)
    except ExtractError as e:
        await send({"type": "error", "message": str(e)})
        return
    except Exception as e:
        log.exception("fetch failed")
        await send({"type": "error", "message": f"Couldn't read that page: {e}"})
        return

    # 2) Optional LLM summary/explainer.
    if mode == "summary":
        await send({"type": "phase", "value": "summarizing"})
        text = await asyncio.to_thread(
            summarize_article, llm, article, cfg.reader.summary_max_chars,
        )
    else:
        text = article.text

    # 3) Synthesize (offline, with progress).
    await send({"type": "phase", "value": "synthesizing"})
    if voice and voice != synth.current_voice:
        try:
            await asyncio.to_thread(synth.swap_voice, voice)
        except Exception:
            log.warning("ignoring bad voice %r", voice)

    def progress(done: int, total: int):
        if not state["alive"]:
            return
        loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(
                send({"type": "progress", "done": done, "total": total})
            )
        )

    audio = await asyncio.to_thread(
        synthesize_article, synth, text,
        gap_sec=cfg.reader.gap_sec, progress=progress,
        should_stop=lambda: not state["alive"],
    )
    if not state["alive"]:
        return   # client gone — don't bother writing/serving the file
    if audio.size == 0:
        await send({"type": "error", "message": "Nothing to read on that page."})
        return

    # 4) Write the WAV and hand back a URL (playback + download).
    out_dir = cfg.reader.output_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.wav"
    await asyncio.to_thread(write_wav, str(out_dir / fname), audio, synth.sample_rate)
    await send({
        "type": "done",
        "title": article.title,
        "audio_url": f"/audio/{fname}",
        "duration_sec": round(len(audio) / synth.sample_rate, 1),
        "word_count": article.word_count,
        "mode": mode,
        # Spoken text for the client transcript panel — summary only (the full
        # article is already on the source page, no need to ship it back).
        "text": text if mode == "summary" else None,
    })


def create_app(cfg: Optional[Config] = None, cert_path: Optional[Path] = None) -> FastAPI:
    cfg = cfg or Config.load()
    models = ReaderModels(cfg)
    out_dir = cfg.reader.output_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield

    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def _no_cache_static(request, call_next):
        resp = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    # Generated article audio (playback + download).
    app.mount("/audio", StaticFiles(directory=str(out_dir)), name="audio")

    @app.get("/")
    async def index():
        dist_index = DIST_DIR / "index.html"
        if dist_index.exists():
            return FileResponse(str(dist_index))
        return FileResponse(str(STATIC_DIR / "index.html"))

    if cert_path is not None:
        @app.get("/cert.pem")
        async def cert():
            return FileResponse(str(cert_path), media_type="application/x-pem-file")

    @app.get("/api/config")
    async def api_config():
        return {
            "voices_available": [{"id": v, "label": label} for v, label in voices_for(cfg.tts.csm)],
            "voice": cfg.tts.active.speaker,
            "model": cfg.ollama.model,
            "default_mode": cfg.reader.default_mode,
        }

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        # Seed the client with current config.
        await websocket.send_json({
            "type": "config",
            "voices_available": [{"id": v, "label": label} for v, label in voices_for(cfg.tts.csm)],
            "voice": cfg.tts.active.speaker,
            "model": cfg.ollama.model,
            "default_mode": cfg.reader.default_mode,
        })
        # The active read job runs as a background task so the receive loop stays
        # free to handle `cancel` (and disconnects) mid-synthesis.
        job_task: Optional[asyncio.Task] = None
        job_state: Optional[dict] = None
        try:
            while True:
                payload = await websocket.receive_json()
                kind = payload.get("type")
                if kind == "cancel":
                    if job_state is not None:
                        job_state["alive"] = False   # aborts synth + silences sends
                    continue
                if kind != "read":
                    continue
                if job_task is not None and not job_task.done():
                    await websocket.send_json({
                        "type": "error", "message": "Still working on the last one…",
                    })
                    continue
                job_state = {"alive": True}
                job_task = asyncio.create_task(
                    _run_read_job(websocket, models, cfg, payload, job_state)
                )

                def _log_job_exc(t: asyncio.Task) -> None:
                    if not t.cancelled() and t.exception() is not None:
                        log.error("read job failed", exc_info=t.exception())

                job_task.add_done_callback(_log_job_exc)
        except WebSocketDisconnect:
            return
        except Exception:
            log.exception("ws error")
        finally:
            # Stop any in-flight synthesis when the socket goes away.
            if job_state is not None:
                job_state["alive"] = False
            if job_task is not None and not job_task.done():
                job_task.cancel()

    return app
