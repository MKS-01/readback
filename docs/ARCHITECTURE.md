# Architecture — readback (v4.2.0)

How the pieces fit together and why. System-level companion to
[CLAUDE.md](../CLAUDE.md) (implementation notes, gotchas, exact knobs) and
[README.md](../README.md) (user-facing). When a specific threshold or flag is in
doubt, CLAUDE.md is authoritative.

## 1. What it is

A fully **on-device**, terminal-first article reader. You paste a URL into the
CLI; the server fetches and extracts the article, optionally summarizes it with
a local LLM, synthesizes the whole thing offline with CSM-1B, and hands back an
audio file the CLI plays via `afplay`. One server process (`readback`) with two
clients: the **terminal CLI** (`src/cli/`, Bun + Ink, macOS) drives *live* reads
over a WebSocket, and the **web dashboard** (`src/dashboard/`, Vue 3) replays
*past* reads over plain REST.

```
URL ─▶ fetch + extract ─▶ [summary] ─▶ chunk ─▶ TTS (offline) ─▶ WAV ─▶ afplay
       (trafilatura)    (mlx-lm)            (CSM-1B / csm-mlx)            └▶ library (SQLite) ─▶ dashboard replay
```

Unlike the real-time voice assistant this project began as, synthesis is **batch,
not streaming**: there is no live turn to keep pace with, so the whole piece is
synthesized up front. That removes audio-underrun and echo entirely and lets
voice quality win over latency.

**Generate once, replay many — and why generation is CLI-side.** The expensive
half (the LLM summary pass + neural TTS) is a *heavy, occasional* task: it wants
the Mac's GPU and unified memory, and you only run it when you actually want a
new read — not every time you want to hear an old one. So readback splits the
two halves deliberately. **Generation** is on-demand from the terminal (LLM + CSM
on the Mac); **replay** is a separate, model-free path that only lists library
rows and serves a finished WAV. This is why the dashboard can stay tiny (no
WebSocket, no models) and why the split deploy is clean — a home Pi hosts the
lightweight UI + audio while the Mac remains the only thing that needs the GPU
(see §6).

## 2. Process & concurrency model

A single FastAPI app (`src/readback/server/server.py`). The event loop stays
responsive while a read job runs because all heavy work is pushed off it:

- **Read jobs run as background `asyncio.Task`s.** The `/ws` receive loop launches
  `_run_read_job` as a task and keeps reading messages, so a `cancel` (or
  disconnect) can be handled *mid-synthesis*. A shared `state["alive"]` flag is
  flipped to abort: it silences further sends and, via `should_stop`, stops the
  synthesis loop so we don't keep burning GPU on audio nobody will hear.
- **Model work runs in threads.** Fetch, summarize, and synthesize are dispatched
  with `asyncio.to_thread`. Synthesis itself is further serialized onto the CSM
  engine's own single executor thread (see §4).
- **One job at a time per socket.** A second `read` while one is running is
  rejected ("still working on the last one").

## 3. The pipeline (`src/readback/pipeline/`)

1. **Extract** (`extract.py`) — `fetch_article(url)` downloads via trafilatura,
   falling back to a browser-UA `urllib` fetch when a site 403s the default
   agent, then `trafilatura.extract(..., favor_precision=True)` pulls the article
   body. Light TTS-prep scrubbing strips URLs, `[12]` citation markers, and
   collapses whitespace so the voice doesn't read markup aloud. Returns an
   `Article{title, text, url}`.
2. **Summarize** (`summarize.py`, Summary mode only) — `summarize_article` calls
   `LLMClient.oneshot(system, user)` with a spoken-explanation system prompt when
   the article fits in one pass (≤ `reader.summary_max_chars`); longer input
   (book scans) is map-reduced across batches of that size instead of truncated.
   The result is clipped to a 250-word ceiling at a sentence boundary
   (`_trim_to_word_ceiling`, which preserves paragraph breaks) — the prompt's
   limit alone is advisory. The tone prompts ask for **2-4 short paragraphs**;
   that is a delivery setting, since step 3 derives its pause lengths from those
   breaks. Full mode skips this and reads `article.text` verbatim.
3. **Chunk + synthesize** (`speak.py`) — `chunk_text` splits into TTS-sized,
   paragraph-respecting chunks (sentence-aware, each chunk's cap randomized in
   [280, 400] chars for varied pacing; over-long sentences split on commas, then
   spaces). `chunk_spans` also reports whether each chunk **ends a paragraph**.
   `synthesize_article` sends those chunks to the engine in **batches**
   of `tts.csm.batch_size` (8) — CSM's frame loop is launch-latency bound, so a
   batch of 8 produces ~4.9x the audio per wall-second that batch 1 does
   (measured ~2x end-to-end on synthesis). Batched prompts are left-padded and
   the pads are **masked out of attention**, so batching changes throughput only,
   never the audio; each row keeps its own delivery temperature. It synthesizes each chunk fully,
   **silence-tidies** it (`_tidy_silence`: trim leading/trailing silence and cap
   internal pauses to ~300 ms), **fades out** the tail (100 ms linear fade via
   `_fade_out_tail`), retries all-silence chunks once, and joins with a pause
   scaled from `reader.gap_sec` by that paragraph flag (`_gap_for`: 2x at a
   paragraph end, 0.6x mid-paragraph, so pacing follows the text). The joined buffer is **peak-normalized** (`_peak_normalize`) so every
   voice lands at the same loudness — clone voices inherit their reference clip's
   level and would otherwise read far quieter than the built-ins.
   `progress(done, total)` fires per chunk; `should_stop()` aborts early.
4. **Serve** — the concatenated float32 buffer is written to
   `reader.output_dir` (a `readback-audio-db/audio/<uuid>.wav` folder beside the
   repo by default — kept next to the library DB, not in a hidden `~/.readback`
   dir) and served at `/audio/<id>.wav` for playback and download. The server
   reports this dir as `audio_dir` in `/api/config` so the CLI can play a
   same-machine WAV without re-downloading.
5. **Record** — the read's metadata (title, summary/excerpt, source URL, mode,
   voice, duration, word count, WAV filename + absolute path, timestamp) is
   written to the SQLite **read library** (`library.py`, `reader.library_db`).
   Best-effort: a DB failure is logged, never breaks playback. This is what the
   web dashboard lists and replays.

## 4. TTS engine (`src/readback/tts/`)

- **`CsmEngine`** (`csm_engine.py`) wraps **CSM-1B via csm-mlx** (`senstella/csm-1b-mlx`),
  float32 @ 24 kHz (Mimi-native — matches the WS contract, no resample).
- **MLX single-thread rule.** MLX binds its GPU stream to the first thread that
  touches the device, so the engine owns a `ThreadPoolExecutor(max_workers=1)` and
  runs **all** model work (load + synth) on it; public methods submit and block.
  This is why concurrent read jobs serialize naturally.
- **Reference conditioning is the voice.** CSM conditions every chunk on a
  reference `Segment` (audio + its exact transcript) cached per voice in
  `_ref_for`. Built-in voices use Sesame read-speech prompts (downloaded from
  `sesame/csm-1b`); **clone voices** (`cfg.voices`) use a local clip; a **LoRA**
  adapter (`cfg.lora_path`), when set, is loaded over the base weights and
  generation switches to **empty context** (the voice lives in the adapter).
- **`Synthesizer`** (`synthesizer.py`) is a thin facade (`synthesize`,
  `synthesize_batch`, `batch_size`, `sample_rate`, `current_voice`, `swap_voice`,
  `set_temperature`, `load`) so the
  server stays engine-agnostic — a future engine is a factory change, not a
  rewrite. `tts.engine` is a single-value enum (`"csm"`).

## 5. LLM (`src/readback/llm/client.py`)

Only **Summary mode** uses the LLM, via `LLMClient.oneshot()` — a single
non-streaming mlx-lm `generate` (low temperature) with `<think>` stripping for
models that emit inline reasoning tags. Full mode skips the LLM entirely. This
is the heaviest, most occasional step (see §1) — it runs only during
generation, never on dashboard replay. The model + tokenizer are loaded lazily
on first call and cached in-process.

The model is switchable at runtime: `llm/models.py` scans downloaded MLX
models in the HuggingFace cache with a RAM-fit verdict and a summary
recommendation (served as `GET /api/models`), and a `model` field on the `read`
WS message swaps `cfg.llm.model` in place — the LLM client detects the change
and unloads/reloads on the next call. The switch is process-wide and not
written back to `config.yaml`.

## 6. Server layer (`src/readback/server/`)

- **Server** (`server.py`) — FastAPI. Serves `/ws`, `GET /api/config`,
  `GET /api/models`, the read-library REST routes, and the generated audio under
  `/audio/`. It additionally mounts the **built dashboard at `/`** when
  `src/dashboard/dist` exists (registered last, so the API/audio/ws routes win);
  in dev that dir is absent so `GET /` is 404 and Vite serves the SPA on :5173.
- **Read library REST** — `GET /api/library?q=&sort=newest|oldest&limit=&offset=`
  returns a page `{items, total, limit, offset}` (limit capped 1–100, default 20;
  the dashboard appends pages via "Load more"); `GET /api/library/{id}`,
  `DELETE /api/library/{id}` (deletes the row + its WAV). All wrap blocking
  sqlite in `asyncio.to_thread`.
- **WS protocol** —
  - client → `read {url, mode, voice?, model?}`, `cancel`
    (`model` swaps the LLM — which serves Summary mode *and* image/book OCR —
    for this and later reads; validated against downloaded MLX models)
  - server → `phase {value}`, `progress {done, total}`,
    `done {title, audio_url, duration_sec, word_count, mode, text?}`, `error {message}`
  - `done.text` carries the spoken summary (Summary mode only) for the
    transcript panel.
- **Terminal client** (`src/cli/`) — Bun + TypeScript + Ink; the sole consumer
  of the WS protocol. It health-checks `/api/config`, fetches `/api/models` for
  its `/model` picker, auto-spawns `readback` when no server is running (and
  kills it on exit only if it spawned it), and plays the finished WAV through
  `afplay`. Its WS client and player are singletons outside the React tree so
  re-renders never tear down the socket.
- **Web dashboard** (`src/dashboard/`) — Vue 3 + Vite + TS; a *second*, separate
  client that speaks **REST only** (not WS): lists/searches/sorts the read
  library, replays each WAV via an HTML5 `<audio>`, and can delete reads. Built
  to static files (served by the server at `/`, or by a Pi host — see §9).

## 9. Pi deployment (`scripts/`)

The Mac is the sole generation host (CSM-1B + mlx-lm + mlx-vlm require MLX/Metal). A
Raspberry Pi can serve as a network-accessible replay host:

- **What runs on Pi** — the same FastAPI server, but TTS + LLM are never
  invoked (no CLI connects to Pi). Pi serves: library REST
  (`/api/library`, `/audio`), and the Vue dashboard (static `dist/`).
- **Why no code changes** — all MLX-dependent imports (csm-mlx in `csm_engine.py`,
  mlx-lm in `client.py`, mlx-vlm in `extract.py`) are lazy (inside function
  bodies, not module-level), so the server imports and starts cleanly on Pi with
  only `requirements-pi.txt` (excludes csm-mlx, mlx-lm, mlx-vlm).
- **`scripts/deploy-pi.sh`** — builds the dashboard on Mac, rsyncs source +
  `dist/` to Pi (excludes `venv/`, `config.yaml`, CLI/finetune/voice dirs), sets
  up a venv with Pi-compatible deps, and starts/restarts the server via PM2.
  PM2 is launched with `--cwd PI_PATH` so `config.yaml`'s relative reader paths
  (`../readback-audio-db/`) resolve correctly regardless of PM2's default cwd.
- **`scripts/sync-pi.sh`** — stops the Pi server (avoids SQLite lock), rsyncs
  WAVs + the library DB from `readback-audio-db/` on Mac to Pi, then restarts.
  **Incremental by default**: a `.last-sync` marker tracks the last successful
  run; only WAVs created/modified since then are transferred (the DB is always
  synced — it's small and rows may be deleted). Pass `--full` to force a full
  sync with `--delete` (cleans orphaned WAVs on Pi).
  Uses SSH keep-alive flags to survive large transfers over Wi-Fi.
- **Config on Pi** — `config.pi.example.yaml` is copied to `config.yaml` on
  first deploy only. Uses the same relative reader paths as Mac; no voices
  section (wav files aren't synced). Pi config edits survive redeployment.
- **Port** — Pi defaults to `:8090`; set `PI_PORT` in `.env` to change.

## 7. Entry point (`src/readback/__main__.py`)

`readback` parses args (`--host/--port/--model/--config`), loads `config.yaml`
(resolved from the working directory by default), and boots uvicorn. The CLI
spawns it with cwd = repo root so the bundled config and its relative
`src/voice/` / `src/finetune/` paths resolve.

## 8. Extension points

- **New TTS engine** — implement the `Synthesizer` surface and branch on
  `tts.engine`.
- **New voice** — a clone clip (`tts.csm.voices`) or a LoRA adapter
  (`tts.csm.lora_path` + `src/finetune/`); no code change.
- **Different extractor / summary prompt** — swap inside `pipeline/extract.py` /
  `pipeline/summarize.py`; the rest of the pipeline is unaffected.
- **New client** — talk the WS protocol (live reads, like the CLI) or just the
  REST library routes (replay past reads, like the dashboard); the server adds
  no per-client code.
