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
            "model"?: str}
            # model: swap the LLM for this read (it does BOTH summary and image/
            # book OCR) — validated vs downloaded MLX models
           {"type":"cancel"}   # abort the in-flight read job (stops synthesis)
  server → {"type":"phase",    "value":"loading"|"fetching"|"summarizing"|"synthesizing"}
           # value is a free-form display string; multi-page OCR streams
           # "reading page N / M" and long-doc summaries "summarizing section N / M"
           {"type":"progress", "done": int, "total": int}
           {"type":"done", "title","audio_url","duration_sec","word_count","mode",
                           "text": str|None (summary text for transcript; None in full mode),
                           "timings": {"model_load"?,"fetch","summarize",
                                       "synthesize","write","total"}}  # secs, 1 dp
           {"type":"error", "message": str}

Each finished read is also recorded in the SQLite read library (library.py) and
exposed over REST for the web dashboard (src/dashboard):
  GET    /api/library?q=&sort=newest|oldest&limit=&offset=  # paged list:
                                               # {items, total, limit, offset}
  GET    /api/library/{id}                     # one full record
  DELETE /api/library/{id}                     # remove the row + its WAV

Feed picks (the CLI's numbered "what's new" list, from `reader.feeds`):
  GET    /api/feed?limit=3&refresh=0           # {items:[{title,url,source,
                                               #   published}], count} — crawled
                                               # live, TTL-cached; refresh=1 forces

The built dashboard (src/dashboard/dist) is mounted at / when present.
"""
from __future__ import annotations

import asyncio
import logging
import time
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
from readback.pipeline.extract import _is_multi_page, classify_source, fetch_multi_page
from readback.pipeline import RECIPE_VERSION
from readback.pipeline.feeds import FeedCache, pick_key
from readback.pipeline.tones import tone_for
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
        self.llm = LLMClient(self.cfg.llm)
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
    t_job_start = time.monotonic()
    timings: dict[str, float] = {}
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
        await send({"type": "error", "message": "Please enter a URL or image path."})
        return

    # Load models on first use (downloads the CSM checkpoint the very first time).
    if not models._loaded:
        await send({"type": "phase", "value": "loading"})
    t0 = time.monotonic()
    await models.ensure_loaded()
    timings["model_load"] = time.monotonic() - t0
    synth, llm = models.synth, models.llm
    assert synth is not None and llm is not None

    # Optional per-read model switch before fetch. One model serves both jobs
    # (summary + image/book OCR), so this is a single knob. Validated against
    # downloaded models and mutated in place — the LLMClient and the vision
    # loader each detect the change and reload on next use.
    model = (payload.get("model") or "").strip()
    if model and model != cfg.llm.model:
        installed = await asyncio.to_thread(installed_model_names, cfg.llm)
        if model in installed:
            cfg.llm.model = model
            log.info("model → %s", model)
        else:
            log.warning("ignoring unknown model %r", model)

    # 0) Cache check — skip the entire pipeline if we already have audio for
    # this exact (url, mode, voice, llm_model) combination.
    effective_voice = voice or synth.current_voice
    effective_model = model if model else cfg.llm.model
    cached = await asyncio.to_thread(
        library.find_cached, url, mode, effective_voice, effective_model,
        RECIPE_VERSION,
    )
    if cached:
        log.info("cache hit: %s (%s)", cached["title"][:50], cached["audio_filename"])
        timings["total"] = time.monotonic() - t_job_start
        await send({
            "type": "done",
            "title": cached["title"],
            "audio_url": f"/audio/{cached['audio_filename']}",
            "duration_sec": cached["duration_sec"],
            "word_count": cached["word_count"],
            "mode": mode,
            "text": cached.get("summary") if mode == "summary" else None,
            "timings": {k: round(v, 1) for k, v in timings.items()},
        })
        return

    # 1) Fetch + extract (URL, single image, or multi-page folder/glob).
    await send({"type": "phase", "value": "fetching"})
    t0 = time.monotonic()
    if _is_multi_page(url):
        def _page_progress(pi: int, tot: int):
            if not state["alive"]:
                return
            # fetch_multi_page fires a final progress(total, total) to signal
            # completion, so clamp — otherwise a 2-page book shows "page 3 / 2".
            msg = {"type": "phase", "value": f"reading page {min(pi + 1, tot)} / {tot}"}
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(send(msg))
            )
        try:
            article = await asyncio.to_thread(
                fetch_multi_page, url, cfg.llm, _page_progress, llm,
            )
        except ExtractError as e:
            await send({"type": "error", "message": str(e)})
            return
        except Exception as e:
            log.exception("multi-page fetch failed")
            await send({"type": "error", "message": f"Couldn't read those pages: {e}"})
            return
    else:
        try:
            article = await asyncio.to_thread(fetch_article, url, cfg.llm, llm)
        except ExtractError as e:
            await send({"type": "error", "message": str(e)})
            return
        except Exception as e:
            log.exception("fetch failed")
            await send({"type": "error", "message": f"Couldn't read that page: {e}"})
            return

    timings["fetch"] = time.monotonic() - t0

    # Reading tone, auto-picked from the source: URL → article (livelier), image /
    # folder → book (measured, opens by naming the chapter/topic). A tone bundles
    # the summary framing with the CSM delivery temperature.
    tone = tone_for(classify_source(url))
    log.info("reading tone: %s", tone.name)

    # 2) Optional LLM summary/explainer — uniform across URL / image / multi-page.
    # Multi-page is now a single continuous document, so it summarizes exactly like
    # a long article (map-reduced when it's a big scan).
    t0 = time.monotonic()
    if mode == "summary":
        await send({"type": "phase", "value": "summarizing"})

        # Long inputs (book scans) map-reduce across several LLM calls; report
        # which section is in flight so a multi-minute summary isn't a silent wait.
        def _summary_progress(done: int, total: int):
            if not state["alive"] or total <= 1:
                return
            msg = {"type": "phase", "value": f"summarizing section {min(done + 1, total)} / {total}"}
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(send(msg))
            )

        text = await asyncio.to_thread(
            summarize_article, llm, article, cfg.reader.summary_max_chars,
            _summary_progress, tone.summary_system,
        )
    else:
        text = article.text
    timings["summarize"] = time.monotonic() - t0

    # 3) Synthesize (offline, with progress). The tone's temperature is the base
    # delivery setting — synthesize_article nudges it per chunk so expression
    # shifts with content instead of staying flat for the whole read (the user's
    # chosen voice is untouched either way — tone shifts pacing, not the voice).
    await send({"type": "phase", "value": "synthesizing"})
    if voice and voice != synth.current_voice:
        try:
            synth.swap_voice(voice)
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

    t0 = time.monotonic()
    audio = await asyncio.to_thread(
        synthesize_article, synth, text,
        gap_sec=cfg.reader.gap_sec, base_temperature=tone.temperature,
        progress=progress, should_stop=lambda: not state["alive"],
    )
    timings["synthesize"] = time.monotonic() - t0
    if not state["alive"]:
        return   # client gone — don't bother writing/serving the file
    if audio.size == 0:
        await send({"type": "error", "message": "Nothing to read on that page."})
        return

    # 4) Write the WAV and hand back a URL (playback + download).
    t0 = time.monotonic()
    out_dir = cfg.reader.output_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.wav"
    audio_path = out_dir / fname
    duration_sec = round(len(audio) / synth.sample_rate, 1)
    await asyncio.to_thread(write_wav, str(audio_path), audio, synth.sample_rate)
    timings["write"] = time.monotonic() - t0

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
            llm_model=cfg.llm.model,
            recipe=RECIPE_VERSION,
        )
        await asyncio.to_thread(library.add, rec)
    except Exception:
        log.exception("failed to record read in library")

    timings["total"] = time.monotonic() - t_job_start
    log.info(
        "read complete: %s | %s | %.1fs audio | %d words | "
        "fetch=%.1fs summarize=%.1fs synthesize=%.1fs write=%.1fs total=%.1fs",
        article.title[:50], mode, duration_sec, article.word_count,
        timings.get("fetch", 0), timings.get("summarize", 0),
        timings.get("synthesize", 0), timings.get("write", 0),
        timings["total"],
    )

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
        "timings": {k: round(v, 1) for k, v in timings.items()},
    })


def create_app(cfg: Optional[Config] = None) -> FastAPI:
    cfg = cfg or Config.load()
    models = ReaderModels(cfg)
    out_dir = cfg.reader.output_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    library = Library(cfg.reader.library_db)
    # Picks are crawled live from `reader.feeds` and cached for feed_ttl_sec so
    # opening the CLI is instant after the first fetch (a crawl is ~5-8 s over
    # three sites). /api/feed?refresh=1 (the CLI's /feed) always re-crawls.
    feeds = FeedCache(cfg.reader.feeds, cfg.reader.feed_ttl_sec)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        asyncio.create_task(models.ensure_loaded())
        yield

    app = FastAPI(lifespan=lifespan)

    # Generated article audio (playback + download).
    app.mount("/audio", StaticFiles(directory=str(out_dir)), name="audio")

    @app.get("/api/config")
    async def api_config():
        return {
            "voices_available": [{"id": v, "label": label} for v, label in voices_for(cfg.tts.csm)],
            "voice": cfg.tts.active.speaker,
            "model": cfg.llm.model,
            "default_mode": cfg.reader.default_mode,
            "audio_dir": str(out_dir),   # where WAVs live (CLI same-machine shortcut)
            "feed_picks": cfg.reader.feed_picks if cfg.reader.feeds else 0,
        }

    @app.get("/api/feed")
    async def api_feed(limit: int = 0, refresh: int = 0):
        """Newest posts across the configured sites — the CLI's numbered picks.

        Blocking network work (urllib + a thread pool per source), so it runs
        off the event loop. A source that fails contributes nothing; an empty
        list just means no picks are shown."""
        limit = max(1, min(limit or cfg.reader.feed_picks, 9))
        try:
            pool = await asyncio.to_thread(feeds.pool, bool(refresh))
        except Exception:
            log.exception("feed fetch failed")
            pool = []
        # Drop what's already in the read library and backfill from the rest of
        # the crawl, so finishing a pick retires it and promotes the next post
        # instead of leaving a stale suggestion (or a shorter list) behind.
        try:
            already = await asyncio.to_thread(library.read_urls)
        except Exception:
            log.exception("library lookup failed; showing unfiltered picks")
            already = set()
        seen = {pick_key(u) for u in already}
        items = [i for i in pool if pick_key(i.url) not in seen][:limit]
        return {"items": [i.to_dict() for i in items], "count": len(items)}

    @app.get("/api/models")
    async def api_models():
        return await asyncio.to_thread(list_models, cfg.llm)

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
            "model": cfg.llm.model,
            "default_mode": cfg.reader.default_mode,
            "audio_dir": str(out_dir),
            # 0 = no feeds configured → the CLI hides the picks section entirely.
            "feed_picks": cfg.reader.feed_picks if cfg.reader.feeds else 0,
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
