"""FastAPI server for the offline article reader.

Pivot (v0.8.0): the real-time voice-assistant cascade (STT / VAD / Smart-Turn /
mic / echo gate) is gone. The server now does one job — turn a URL into audio:

    URL → fetch + extract article → (optional LLM summary) → CSM TTS (offline)
        → write WAV → serve it to the CLI player

Synthesis is offline, so there is no real-time constraint: we synthesize the
entire piece, then play. Progress streams over a WebSocket; the finished WAV is
served from `cfg.reader.output_dir`.

WS protocol (/ws):
  client → {"type":"read", "url": str, "mode": "full"|"summary", "voice"?: str,
            "model"?: str}   # model: swap the summary LLM (validated vs Ollama)
           {"type":"cancel"}   # abort the in-flight read job (stops synthesis)
  server → {"type":"phase",    "value":"loading"|"fetching"|"summarizing"|"synthesizing"}
           {"type":"progress", "done": int, "total": int}
           {"type":"done", "title","audio_url","duration_sec","word_count","mode",
                           "text": str|None (summary text for transcript; None in full mode)}
           {"type":"error", "message": str}

Each finished read is also recorded in the SQLite read library (library.py) and
exposed over REST for the web dashboard (src/dashboard):
  GET    /api/library?q=&sort=newest|oldest&limit=&offset=  # paged list:
                                               # {items, total, limit, offset}
  GET    /api/library/{id}                     # one full record
  DELETE /api/library/{id}                     # remove the row + its WAV
The built dashboard (src/dashboard/dist) is mounted at / when present.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from readback.config import Config
from readback.library import Library, ReadRecord
from readback.llm.client import LLMClient
from readback.llm.models import installed_model_names, list_models
from readback.pipeline import ExtractError, fetch_article
from readback.pipeline.speak import synthesize_article, write_wav
from readback.pipeline.summarize import summarize_article
from readback.tts.csm_engine import voices_for
from readback.tts.synthesizer import Synthesizer

# The built Vue dashboard (src/dashboard/dist), if present. Mounted at / so the
# library UI is served by the same process that makes the audio. Absent in dev
# (Vite serves it on :5173, proxying /api + /audio here) → GET / stays 404.
_DASHBOARD_DIST = Path(__file__).resolve().parents[2] / "dashboard" / "dist"

log = logging.getLogger("readback.server")


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
    library: Library, state: Optional[dict] = None,
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
    model = (payload.get("model") or "").strip()
    if model and model != cfg.ollama.model:
        installed = await asyncio.to_thread(installed_model_names, cfg.ollama)
        if model in installed:
            cfg.ollama.model = model   # oneshot() reads cfg.model per call
            log.info("summary model → %s", model)
        else:
            log.warning("ignoring unknown model %r", model)
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
    audio_path = out_dir / fname
    duration_sec = round(len(audio) / synth.sample_rate, 1)
    await asyncio.to_thread(write_wav, str(audio_path), audio, synth.sample_rate)

    # 4b) Record the read in the library (powers the dashboard). A DB hiccup must
    # never break playback, so this is best-effort + logged.
    try:
        rec = ReadRecord(
            id=audio_path.stem,
            title=article.title,
            summary=text if mode == "summary" else None,
            excerpt=(article.text or "").strip()[:300],
            source_url=url,
            mode=mode,
            voice=synth.current_voice,
            duration_sec=duration_sec,
            word_count=article.word_count,
            audio_filename=fname,
            audio_path=str(audio_path),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        await asyncio.to_thread(library.add, rec)
    except Exception:
        log.exception("failed to record read in library")

    await send({
        "type": "done",
        "title": article.title,
        "audio_url": f"/audio/{fname}",
        "duration_sec": duration_sec,
        "word_count": article.word_count,
        "mode": mode,
        # Spoken text for the client transcript panel — summary only (the full
        # article is already on the source page, no need to ship it back).
        "text": text if mode == "summary" else None,
    })


def create_app(cfg: Optional[Config] = None) -> FastAPI:
    cfg = cfg or Config.load()
    models = ReaderModels(cfg)
    out_dir = cfg.reader.output_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    library = Library(cfg.reader.library_db)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield

    app = FastAPI(lifespan=lifespan)

    # Generated article audio (playback + download).
    app.mount("/audio", StaticFiles(directory=str(out_dir)), name="audio")

    @app.get("/api/config")
    async def api_config():
        return {
            "voices_available": [{"id": v, "label": label} for v, label in voices_for(cfg.tts.csm)],
            "voice": cfg.tts.active.speaker,
            "model": cfg.ollama.model,
            "default_mode": cfg.reader.default_mode,
        }

    @app.get("/api/models")
    async def api_models():
        return await asyncio.to_thread(list_models, cfg.ollama)

    # ── Library (dashboard) ──────────────────────────────────────────────
    @app.get("/api/library")
    async def api_library(q: str = "", sort: str = "newest", limit: int = 20, offset: int = 0):
        sort = sort if sort in ("newest", "oldest") else "newest"
        limit = max(1, min(limit, 100))   # cap the page size
        offset = max(0, offset)
        q = q.strip()
        items = await asyncio.to_thread(library.list, q, sort, limit, offset)
        total = await asyncio.to_thread(library.count, q)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @app.get("/api/library/{read_id}")
    async def api_library_get(read_id: str):
        rec = await asyncio.to_thread(library.get, read_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="No such read.")
        return rec

    @app.delete("/api/library/{read_id}")
    async def api_library_delete(read_id: str):
        audio_path = await asyncio.to_thread(library.delete, read_id)
        if audio_path is None:
            raise HTTPException(status_code=404, detail="No such read.")
        # Best-effort unlink of the WAV; the row is already gone either way.
        try:
            Path(audio_path).unlink(missing_ok=True)
        except Exception:
            log.warning("could not delete WAV %s", audio_path)
        return {"deleted": True}

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
                    _run_read_job(websocket, models, cfg, payload, library, job_state)
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

    # Serve the built Vue dashboard at / when present (registered last so the
    # API/audio/ws routes above take precedence). Absent in dev → GET / stays 404.
    if _DASHBOARD_DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(_DASHBOARD_DIST), html=True), name="dashboard")
        log.info("serving dashboard from %s", _DASHBOARD_DIST)

    return app
