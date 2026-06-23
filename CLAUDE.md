# readback — Project Context

An **offline article reader**, terminal-first. Paste a URL → fetch + extract the
article → optionally summarize it with a local LLM → synthesize the whole thing
with **CSM-1B** (Sesame, via `csm-mlx`) → play it in the terminal via `afplay`.
All on-device on Apple Silicon. No cloud, no API keys.

**History:** this began as a real-time voice assistant (`local-tts`) and was
**pivoted to an article reader in v0.8.0**, then **renamed to `readback`**. The
entire live cascade — Parakeet STT, Smart-Turn, webrtcvad, mic capture, echo
gate, wake-word, personas, tools, Obsidian export — was removed. If you see those
referenced anywhere, it's stale: the current package is just
`llm/ pipeline/ tts/ server/`, and the server wires none of the
tools/persona/obsidian machinery (the `tools/` module and the streaming/
tool-calling LLM plumbing were removed in the v0.8.0 cleanup).

**See [ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the system-level view (pipeline,
concurrency model, extension points). This file holds implementation notes,
gotchas, and exact knobs.

## Hardware

- Apple M5 Pro, 48 GB unified memory (primary target). No CUDA.
- **MLX/Metal (20-core GPU)** runs CSM-1B TTS + the summary LLM (mlx-lm) + vision OCR (mlx-vlm) — all in-process.
- **MLX is not multi-thread safe** — its default GPU stream binds to the thread
  that first touches the device, so `CsmEngine` owns a single-thread executor and
  runs all model work on it (see TTS section).

## Stack

- **Extraction**: `trafilatura` (URL → clean article text) + a browser-UA urllib
  fallback for sites that 403 the default agent. Local images (`.png/.jpg/.heic/…`)
  → mlx-vlm vision OCR (config-driven model). Folder or glob → multi-page
  mode: pages OCR'd in natural-filename order and stitched into one continuous
  Article (a scanned page is a page, not a chapter — no synthetic headers), then
  summarized/read like any article.
 - **LLM**: **mlx-lm** (in-process on MLX/Metal), default
  **`mlx-community/Qwen3.5-9B-4bit`** (chain-of-thought disabled via
  `enable_thinking=False`; `<think>` stripping as backup — see LLM section). Used
  **only by Summary mode** (`LLMClient.oneshot`) + title generation. Vision OCR
  uses **mlx-vlm** (default `mlx-community/Qwen2.5-VL-7B-Instruct-4bit`).
  `/model` can switch per-read; any downloaded MLX chat model works.
- **TTS**: **CSM-1B** (`senstella/csm-1b-mlx`, Sesame Conversational Speech Model)
  via **`csm-mlx`** on Metal, bf16, 24 kHz native. 2 built-in reading voices +
  clone-condition voices + optional LoRA fine-tuning. English-best.
- **Server**: FastAPI + WebSocket (`/ws`) for live reads, plus a small REST
  surface (config / models / read-library). Two clients: the terminal CLI (the
  sole `/ws` consumer) and the web dashboard (REST + static, served at `/`).
- **Terminal CLI**: Bun + TypeScript + Ink (React for CLIs) in `src/cli/` — the sole
  client of the `/ws` protocol; `afplay` playback, macOS-only.

## Project Structure

```
readback/
├── pyproject.toml             # v3.2.0; csm-mlx (git dep) + mlx-lm + mlx-vlm + trafilatura + fastapi
├── config.yaml                # user-editable: llm / tts.csm / reader blocks (cwd-resolved)
├── .env.example               # Pi deployment config template (PI_USER/PI_HOST/PI_PATH/PI_PORT etc.)
│                              # ⚠ copy to .env (gitignored) and fill in real values — never commit .env
├── config.pi.example.yaml     # Pi config template: built-in speaker, same relative reader paths as Mac,
│                              # no voices section (wav files aren't on Pi). deploy-pi.sh copies to
│                              # config.yaml on Pi on first deploy only; subsequent deploys preserve edits.
├── requirements-pi.txt        # Pi-compatible deps — excludes csm-mlx (MLX/Metal = Apple Silicon only).
│                              # Only what's actually imported at server startup: fastapi, uvicorn,
│                              # pydantic, pyyaml, python-multipart, numpy. trafilatura/
│                              # soundfile/huggingface-hub are lazy imports (never called on Pi).
├── scripts/
│   ├── setup.sh               # one-command first-time setup (the README "Getting started"
│   │                          # path): platform/Python check → .venv + pip install -e . →
│   │                          # CLI + dashboard build (Bun) → optional MLX model download +
│   │                          # CSM-1B weight pre-warm. Idempotent; reads default model from
│   │                          # config.yaml. macOS/Apple-Silicon only.
│   ├── deploy-pi.sh           # build dashboard → rsync source+dist → venv+pip → PM2 start/restart.
│   │                          # Excludes venv/ and config.yaml from rsync so Pi state is preserved.
│   │                          # PM2 started with --cwd PI_PATH so relative config paths resolve.
│   └── sync-pi.sh             # stop Pi server → rsync WAVs + SQLite DB Mac→Pi → pm2 restart.
│                              # Incremental by default: a .last-sync marker in readback-audio-db/
│                              # tracks the last run; only new/modified WAVs are transferred.
│                              # --full forces a full sync (with --delete to clean orphans on Pi).
│                              # SSH keep-alive flags prevent drop on large transfers over Wi-Fi.
├── README.md                  # user-facing (GitHub landing; stays at root)
├── tests/                     # 38 pytest cases — PURE LOGIC only (no MLX/CSM/GPU): chunking,
│                              # silence-tidy, fade-out, extract scrub, library + cache, think-stripper,
│                              # tones, map-reduce batching. See docs/TESTS.md for the full catalogue.
│                              # Config in pyproject.toml; runnable on Linux (requirements-pi.txt subset).
├── .github/workflows/
│   ├── ci.yml                # runs the pytest suite on push + PR, Python 3.10 + 3.12 on Ubuntu;
│   │                          # installs requirements-pi.txt + pytest (NOT the package — csm-mlx/
│   │                          # mlx won't install on Linux). JUnit summary on PRs via test-summary/action.
│   └── pages.yml              # deploys src/landing-page/ to GitHub Pages — ONLY on
│                              # push to main (i.e. after a PR merges) AND only when
│                              # the page or one of its exact media files changed
│                              # (narrow `paths`); job gated to main. Copies wordmark
│                              # + CLI/dashboard shots + sample WAV from docs/media/.
│                              # ⚠ new page media → add to BOTH `paths` + the cp list
├── docs/
│   ├── ARCHITECTURE.md        # system-level view
│   ├── SETUP.md               # end-to-end setup guide
│   ├── PLAN.md                # planning history (newest entry on top)
│   ├── ROADMAP.md             # roadmap — planned + recently shipped (single open-item tracker)
│   ├── TESTS.md               # test catalogue — every case grouped by module, what it guards
│   ├── JOURNEY.md             # agent-first devlog (scaffold; user fills prose)
│   └── media/                 # README screenshots + sample WAV + wordmark.png
│                              # (brand banner; regen: make_wordmark.py — keep in
│                              # sync with the CLI banner in Header.tsx)
│
└── src/
    ├── finetune/              # LoRA fine-tune pipeline (README + transcribe.py + data/)
    ├── voice/                 # reference clips for clone voices; *.wav gitignored
    │                          # (exception: committed voice_codeword.wav,
    │                          # the active codeword reference)
    ├── design-system/         # shared design system — canonical source for the Ghost palette.
    │   ├── tokens/            # colors.css, typography.css, spacing.css, motion.css, base.css
    │   │                      # Dashboard imports via @import; landing page inlines (deployed
    │   │                      # standalone). CLI mirrors via theme.ts (Ink, no CSS).
    │   ├── components/        # 9 React JSX specimen components (Badge, Button, PromptLine,
    │   │                      # SearchInput, SeekBar, WaveformPlayer, ReadCard, Wordmark,
    │   │                      # SectionHeader). Bundled into _ds_bundle.js.
    │   ├── ui_kits/           # 3 full-page recreations (terminal, dashboard, landing) that
    │   │                      # compose the components into interactive demos.
    │   ├── templates/         # dc-runtime template wrappers (for Claude Design Components).
    │   ├── index.html         # single-page design system viewer — tokens, components, kits.
    │   │                      # Serve with `python3 -m http.server` and open in browser.
    │   ├── styles.css         # base stylesheet importing all token layers.
    │   └── _ds_bundle.js      # pre-built bundle of all components (bun build).
    ├── dashboard/             # web library UI (Vue 3 + Vite + TS); REST + static client
    │                          # (search/sort/replay/delete past reads), NOT a /ws client.
    │                          # src/{App,api,styles}.* + components/; build → dist/ (gitignored),
    │                          # which server.py mounts at / when present. Tokens from design-system/.
    ├── landing-page/          # static marketing site (mks-01.github.io/readback) —
    │                          # index.html + style.css, vanilla inline JS (waveform
    │                          # player, screenshot stepper w/ rAF progress bar, scroll
    │                          # reveal + staggered Features). Tokens inlined (deployed
    │                          # standalone); keep in sync with design-system/. Trimmed to hook+redirect:
    │                          # hero · Hear it · See it work · Features · Dive-in (GitHub
    │                          # links) — deep docs live in the repo, not duplicated here.
    │                          # NOT a web client; media/ gitignored (preview of docs/media).
    │                          # Deployed by pages.yml; refresh via the landing-page skill.
    ├── cli/                   # terminal client (Bun + Ink); sole /ws client
    │   ├── package.json       # readback-cli (version-synced); ink + ink-text-input
    │   ├── install.sh         # one-command build: bun compile → ~/.local/bin/readback-cli
    │   └── src/               # index.tsx (boot + resize repaint), app.tsx (screen
    │                          # switch), theme.ts (Ghost + BLUE accent),
    │                          # server.ts (spawn), ws.ts, player.ts (afplay + seek),
    │                          # prefs.ts, components/{Header,UrlInput,StatusLine,
    │                          # BusyView,PlayerView,ModelList,LibraryView}.tsx
    └── readback/              # python package (src layout; wheel packages src/readback)
        ├── __main__.py        # `readback` CLI: argparse --host/--port/--model/--config, uvicorn boot
        ├── config.py          # Pydantic config: LLMConfig / OcrConfig / CsmTTSConfig
        │                      # (+ CsmVoicePrompt) / ReaderConfig; load() resolves clone wav +
        │                      # lora + library_db, migrates old llm.vision_model → ocr.model
        ├── library.py         # SQLite read library (stdlib sqlite3): Library class
        │                      # (add/list/get/delete/find_cached over a `reads` table) — powers
        │                      # the dashboard + the read cache
        ├── llm/
        │   ├── client.py      # LLMClient.oneshot() for summary + the <think> stripper
        │   └── models.py      # MLX model listing (HF cache scan) + RAM-fit verdict (GET /api/models)
        ├── pipeline/
        │   ├── extract.py     # fetch_article (URL/image) + fetch_multi_page (folder/glob);
        │   │                  # trafilatura + UA fallback; mlx-vlm vision OCR; TTS-prep scrub
        │   ├── tones.py       # reading tones: Tone(summary_system, temperature);
        │   │                  # ARTICLE (URL) / BOOK (image) + tone_for(kind)
        │   ├── summarize.py   # summarize_article: LLM oneshot/map-reduce → spoken
        │   │                  # explanation; tone `system` prompt selectable
        │   └── speak.py       # chunk_text + synthesize_article + _tidy_silence + _fade_out_tail + _peak_normalize + write_wav
        ├── tts/
        │   ├── csm_engine.py  # CsmEngine (csm-mlx); single-thread MLX executor; _ref_for
        │   │                  # (built-in prompt / clone clip / empty-for-LoRA); voices_for
        │   └── synthesizer.py # Synthesizer facade over CsmEngine
        └── server/
            └── server.py      # FastAPI app, /ws, read-job task + cancel, /audio serving
```

## Critical Implementation Notes

### Server pipeline (`server/server.py`)

- **Read jobs run as background tasks.** The `/ws` loop launches `_run_read_job`
  via `asyncio.create_task` and keeps receiving, so a `cancel` is handled
  mid-job. Cancel/disconnect flips `state["alive"] = False`, which silences sends
  and (via `should_stop`) aborts synthesis. One job per socket; a second `read`
  while busy returns an error.
- **Read cache** (step 0, before fetch): `library.find_cached(url, mode, voice,
  llm_model)` checks for an existing WAV matching the exact cache key. On hit the
  entire pipeline is skipped — `done` fires immediately with the cached record.
  The cache key includes the LLM model so a `/model` switch doesn't replay stale
  audio. The lookup is backed by a composite index (`idx_reads_cache`). A hit
  requires the WAV file to still exist on disk (deleted WAVs are misses).
- **Phases** stream as `phase` messages (`loading` → `fetching` → `summarizing` →
  `synthesizing`), then per-chunk `progress {done, total}`, then `done`.
- **`done` payload**: `{title, audio_url, duration_sec, word_count, mode, text,
  timings}`. `text` is the spoken summary **only in Summary mode** (None in Full)
  — it feeds the client transcript panel; the full article isn't shipped back (it's
  on the source page). `timings` = `{fetch, summarize, synthesize, write, total}`
  (seconds, rounded to 1 dp) — server-side instrumentation for profiling reads.
- Models (`Synthesizer` + `LLMClient`) load via `ReaderModels.ensure_loaded`
  (downloads the CSM checkpoint the first time). The **lifespan hook kicks off
  `ensure_loaded()` as a background task at server boot** so weights are warm
  before the first read (the CLI spawns the server seconds ahead of the first
  URL); the first read still awaits the same guarded `ensure_loaded` if it lands
  early. The `LLMClient` instance is reused across the pipeline (passed into
  `fetch_article`/`fetch_multi_page` for title generation, avoiding per-call
  reinstantiation). `set_temperature` and `swap_voice` are plain attribute
  mutations (no `asyncio.to_thread` needed — they don't touch MLX).
- **Read library persist.** Step 4b (after `write_wav`) records the read in the
  SQLite library via `library.add(...)` (best-effort — wrapped in try/except +
  logged; a DB failure must never break playback). Full mode stores `excerpt`
  (article text[:300], summary=None); Summary mode stores both. `id` = the WAV's
  uuid stem. `llm_model` stores the summary LLM used (part of the cache key).
- **Library REST** (read-only + delete, all `asyncio.to_thread` over blocking
  sqlite): `GET /api/library?q=&sort=newest|oldest&limit=&offset=` →
  **paged** `{items, total, limit, offset}` (limit capped 1–100, default 20;
  `total` is the full match count, independent of the page),
  `GET /api/library/{id}`, `DELETE /api/library/{id}` (row, then unlinks the WAV).
- **Browser UI is back — for the dashboard only.** When `src/dashboard/dist`
  exists it's mounted at `/` (`StaticFiles(html=True)`, registered LAST so
  `/api`/`/audio`/`/ws` win); absent (dev) → `GET /` is 404 and Vite serves the
  SPA on :5173, proxying to :8000. This is the lone exception to the v2.0.0
  "pure backend" rule — a separate read-only library, NOT the removed read-UI.

### Pipeline (`pipeline/`)

- **Extract** (`extract.py`): trafilatura first, browser-UA urllib fallback on
  empty/403. `_clean_for_tts` strips `https?://…`, `[12]` citation markers, and
  collapses whitespace. Missing title → slug from the URL tail. Local images →
  `_ocr_via_mlx` (sips converts HEIC/TIFF/BMP/WebP → JPEG; mlx-vlm vision model
  from `cfg.ocr.model`). **Multi-page** (`_is_multi_page` → folder or
  glob): `_collect_images` natural-sorts by filename, `fetch_multi_page` OCRs each
  page (the vision model is loaded once and cached across calls) and joins
  the pages with a single space at each seam (a book sentence runs across page
  breaks; within-page paragraphs survive). Returns one continuous Article — the
  server then summarizes/reads it through the **same** step 2 as a URL article (no
  special-casing; long scans are map-reduced by `summarize_article`, not truncated).
  Progress fires `reading page N / M` via the existing `phase` WS channel.
- **Tones** (`tones.py`): a `Tone` bundles a summary framing prompt + a CSM
  delivery `temperature`. `classify_source(src)` → `"book"` (image / folder / glob)
  or `"article"` (URL); `tone_for(kind)` → `BOOK` (measured, **0.6**, opens by
  naming the chapter/topic) or `ARTICLE` (livelier explainer, **0.8**). Auto,
  server-side, invisible to the CLI — **no `/tone` override or config yet** (room
  for a 3rd tone). Both `summary_system` prompts carry a **hard ~250-word
  (10–15 sentence) length ceiling** so the spoken summary stays a briefing, not a
  retelling (paired with `oneshot`'s `max_tokens` bound). ⚠ Tone shifts
  *delivery temperature*, NOT the voice — the user's
  `/voice` is untouched. Book sources also take their **title from the first ~3 OCR
  lines** (`_book_title_from_text`), which the BOOK prompt then leads with.
- **Summarize** (`summarize.py`): short body (≤ `reader.summary_max_chars`, default
  16000) → one `oneshot` with the spoken-explanation prompt (`_summarize_once`).
  The framing prompt is the tone's `system` (passed by the server; defaults to the
  article tone).
  Longer input (book scans) → **map-reduce** (`_map_reduce`): `_batches` packs the
  text into ≤`max_chars` batches (paragraph → sentence → hard-cut), each condensed
  with `_MAP_SYSTEM`, the digests joined and reduced via `_summarize_once`;
  recurses (depth ≤ 3) if the joined digests still overflow. ⚠ This **replaced** the
  old hard truncation that silently dropped everything past ~10-12 pages. Optional
  `progress(done, total)` fires per batch in the map phase (server → `summarizing
  section N / M`). Returns the article text unchanged if the LLM produced nothing.
- **Chunk + synth** (`speak.py`):
  - `chunk_text` — paragraph-respecting, sentence-aware merge up to `_MAX_CHARS`
    (280); over-long single sentences split on commas; sub-`_MIN_CHARS` (8)
    fragments stitched onto neighbors.
  - `_tidy_silence` — ⚠ **this is what removes the halting feel.** CSM, conditioned
    on the casual/disfluent Sesame prompt, emits long mid-utterance pauses;
    `_tidy_silence` trims leading/trailing silence (−40 dB threshold) and caps any
    internal silent run to `max_pause_ms` (300). Model-agnostic post-processing.
  - `synthesize_article` — synth each chunk, tidy, fade-out tail, join with
    `reader.gap_sec` (0.18 s) gaps; `progress`/`should_stop` hooks; a chunk that
    throws is skipped, not fatal. **Degenerate-chunk guard:** if `_tidy_silence`
    returns empty (all silence), synthesis is retried once before dropping the chunk.
  - `_fade_out_tail` — 100 ms linear fade-out on each chunk's tail before the
    silence gap, smoothing the voiced→silence transition (no hard cut → click).
  - `_peak_normalize` — ⚠ **levels every voice to the same loudness.** CSM matches
    the energy of its reference clip, so clone voices (quiet refs) came out ~18 dB
    softer than the near-full-scale built-in prompts. The concatenated buffer is
    peak-normalized to **0.95** before return (no limiter — CSM output has no stray
    transients). Applied unconditionally; clean speech so it's safe.

### TTS — CSM-1B (`tts/csm_engine.py`, `tts/synthesizer.py`)

- **Engine: `csm-mlx`** (`senstella/csm-1b-mlx`, `ckpt.safetensors`). float32 @
  24 kHz, cast to **bf16** by default (`cfg.precision`: `bf16`/`fp16`/`fp32`).
  Offline, so `fp32` is viable for max quality.
- **MLX single-thread:** `ThreadPoolExecutor(max_workers=1)` owns load + all
  synth. `_impl` methods run ON that thread and must never re-submit. Never call
  `mx` ops or the engine's `_impl` from another thread.
- **`_ref_for(voice)` — the voice selector**, cached per voice:
  1. `cfg.lora_path` set → returns **`[]`** (empty context); the fine-tuned voice
     lives in the adapter (per the csm-mlx FINETUNING preset).
  2. voice is a `cfg.voices` clone → builds the `Segment` from the **local clip +
     its `ref_text`**.
  3. otherwise → built-in reading prompt downloaded from `sesame/csm-1b`
     (`read_speech_a/b.wav` + hardcoded transcripts).
  `ref_max_sec` (None = full clip) trims the reference audio AND its transcript
  together — a mismatched (audio, text) pair garbles the voice.
- **LoRA** (`_load_impl`): when `cfg.lora_path` is set, `csm_mlx.load_adapters`
  is applied over the base weights after the dtype cast.
- **Voices**: `SUPPORTED_VOICES` = 2 built-ins (`conversational_a` ★ female,
  `conversational_b` male). `voices_for(cfg)` = built-ins + `cfg.voices` clones;
  used by both the engine and the server's picker.
  `swap_voice` validates against `voices_for`. `temperature` tunes **delivery**
  (lower = composed/measured, higher = livelier); **below ~0.55 with a short
  (<5 s) reference the clone destabilizes** (rambles/repeats). `set_temperature`
  (engine + Synthesizer) sets it per-read — `_make_sampler` reads `cfg.temperature`
  fresh each synth, so it takes effect on the next call with no reload (the server
  uses it to apply the reading tone; see Tones).
- The reader synthesizes in **batch only** (`synthesize`); offline reads get no
  benefit from streaming, so the csm-mlx `stream_generate` path was removed.

### Voice cloning & fine-tuning

- **Clone-condition** (`tts.csm.voices`, `CsmVoicePrompt`): a local clip's timbre +
  tone are reproduced. Fields: `name`, `label`, `wav` (resolved relative to
  `config.yaml`), `ref_text` (the clip's **exact** transcript), `speaker`. The
  bundled config ships a sample `codeword` voice (default; `temperature` 0.7). Its
  active reference is `src/voice/voice_codeword.wav` — a 12 s clip CSM-bootstrapped
  (2026-06-16) from a one-off clone, so **no source audio is retained** and the
  `ref_text` exactly matches what's spoken (reliable conditioning). Committed past
  the gitignore.
- **The reusable procedure lives in `.claude/skills/csm-voice`** — clone, tune
  delivery, or LoRA fine-tune. Read it before any voice work.
- **LoRA fine-tune** pipeline in `src/finetune/` (`README.md`): `transcribe.py` →
  `csm-mlx finetune convert` → `csm-mlx finetune lora sft` → set `tts.csm.lora_path`.
  Tuned for M5/48 GB (batch 1 + grad-accum + checkpointing; full fine-tune is
  Mac-Studio-class RAM).

### Config (`config.py`)

- `LLMConfig{model}` (`llm:`) — HuggingFace ID for mlx-lm (summary + title gen).
- `OcrConfig{model}` (`ocr:`) — HuggingFace ID for mlx-vlm (image / book-scan OCR).
  ⚠ OCR has its **own** top-level section (not under `llm:`) — different job,
  different model family. `Config.load()` auto-migrates an old `llm.vision_model`
  → `ocr.model`. On the wire the field stays `vision_model` (WS read /
  `/api/config`) and `current_vision` (`/api/models`) — only the YAML/config
  object moved.
- `CsmTTSConfig{precision, speaker, temperature, top_k, max_audio_length_ms,
  ref_max_sec, voices, lora_path}`. The checkpoint (`senstella/csm-1b-mlx`) is
  fixed in the engine.
- `ReaderConfig{output_dir, default_mode, gap_sec, summary_max_chars,
  library_db}`. `output_dir` + `library_db` default to a sibling
  `readback-audio-db/` folder next to the repo (`../readback-audio-db/audio` and
  `../readback-audio-db/library.db`) — audio + DB in one visible, back-up-able
  place, NOT a hidden `~/.readback` dir. ⚠ Defaults use **`../` relative
  notation** (no personal absolute path baked into the public repo).
- `Config.load()` resolves clone `wav` paths + `lora_path` relative to the config
  dir, and resolves **`output_dir` + `library_db`** the same way then `.resolve()`s
  them to clean absolute paths (`~` expands; absolute paths as-is). The absolute
  `output_dir` is what the server stores in each row's `audio_path` and reports as
  `audio_dir` in `/api/config` + the WS `config` message (the CLI's same-machine
  playback shortcut — see CLI section).

### LLM (`llm/client.py`)

- The reader uses only **`oneshot(system, user, max_tokens=1024)`** — one
  non-streaming mlx-lm `generate`, `temperature=0.4`, `<think>` stripped.
- ⚠ **`enable_thinking=False` is passed to `apply_chat_template`** — this is the
  single biggest summary/audio speed lever. Qwen3/3.5 default to chain-of-thought
  and otherwise spend the WHOLE token budget on a visible "Thinking Process:"
  preamble (UNTAGGED, so `_ThinkStripper` can't catch it → it gets read aloud) and
  get truncated before the real answer. With it off a 215-word article summarizes
  in **~4 s / ~190 words** instead of **~76 s / ~2760 words**. The `/no_think`
  token is ignored by the MLX builds — only the template kwarg works. Wrapped in
  try/except so a model whose template rejects the kwarg still runs (any
  user-picked `/model`).
- ⚠ **`max_tokens=1024`** (was 4096) caps runaway generation — a spoken summary is
  ~190–250 words ≈ <600 tokens, so it's a safety bound, not a target. Belt to the
  `enable_thinking=False` suspenders.
- `_ThinkStripper` removes `<think>…</think>` across chunk boundaries. The
  streaming/tool-calling methods and the `tools/` module were removed in the
  v0.8.0 cleanup.
- `llm/models.py` (`GET /api/models` + the `read` message's `model`/`vision_model`
  fields): scans downloaded MLX models in the HuggingFace cache with a RAM-fit
  verdict (need ≈ size×1.2+1 GiB; good ≤50% / tight ≤75% of total RAM via
  `sysctl hw.memsize`) and recommends the largest good-fit chat model. Each model
  is tagged `chat`/`vision`; the response carries `current` (summary) +
  `current_vision`. A per-read `model` mutates `cfg.llm.model` and `vision_model`
  mutates `cfg.ocr.model`, in place (process-wide, like `swap_voice`;
  **not** written back to `config.yaml`) — the LLM client / vision loader detect
  the change and reload on next use (`oneshot()` / `_ocr_via_mlx`). The read job
  scans installed models once when either changed.

### CLI (`src/cli/`)

- **The `/ws` client** — Bun + Ink, same protocol as the server, zero
  Python changes. `ws.ts` and `player.ts` are module singletons outside the
  React tree (so re-renders never tear down the socket/player). Flags:
  `--host` (127.0.0.1), `--port` (8000), `--no-spawn`.
- **Auto-spawn lifecycle** (`server.ts`): health-check `GET /api/config`; if no
  server, spawn `readback` (prefers `.venv/bin/readback`, cwd = repo root so
  `config.yaml` resolves), wait up to 60 s; on exit kill it **only if we spawned
  it** — `stopServer` **SIGKILLs outright** (no busy-wait). ⚠ uvicorn's graceful
  SIGTERM hangs on the open `/ws`, and the old SIGTERM-then-busy-wait-1.5 s-then-
  SIGKILL was self-defeating: the synchronous `Bun.sleepSync` busy-wait blocks the
  very event loop Bun needs to reap the child, so `exitCode` never updated and the
  loop always ran its full deadline — that wait was the entire quit delay. SIGKILL
  (uncatchable, ~instant, no orphan) is right for our ephemeral, stateless server.
  `shutdown` (`index.tsx`) calls `closeActiveSocket()` (a `ws.ts` module singleton)
  first so the client `/ws` tears down cleanly on every exit path, including signal
  handlers where ink's unmount doesn't run. A SIGKILL of the CLI itself orphans
  the spawned server.
- **Ink screen model** (`app.tsx`): `useReducer` switches one mounted screen
  (`input` | `busy` | `player` | `library` | `quitting`), so key handlers only
  land on the active screen. Slash commands: `/voice`, `/mode`, `/model` (lists
  downloaded MLX **chat** models via `GET /api/models` with a RAM-fit verdict +
  summary recommendation, switches the summary LLM per-read), `/vision` (same
  flow filtered to **vision** models — switches the image/book OCR model
  per-read; `handlePickModel(kind)` + `ModelList kind` serve both, no
  recommendation marker for vision), `/library` (alias `/lib` —
  `GET /api/library?sort=newest&limit=20&offset=N`, arrow-key nav, Enter to
  replay, `d` twice to delete), `/help`, `/quit`; esc cancels a read.
  `q` when the URL input field is empty triggers quit — intercepted in
  `UrlInput.onChange` before the controlled value updates. Quit path:
  `dispatch("quitting")` → braille spinner renders for 300 ms → `shutdown()` +
  `exit()` (the delay lets Ink paint one frame before tearing down).
  **Input guard** (`handleSubmit`): an input is a command iff its FIRST token is
  a known command word (`KNOWN_COMMANDS`, kept in sync with `handleCommand`'s
  switch). ⚠ Match on the first token only — the arg may contain a `/` (e.g.
  `/model mlx-community/Qwen…`), so the old "no second `/`" heuristic wrongly
  routed `/model <hf-id>` to the read pipeline. Absolute paths (`/Users/…`),
  globs (`*`/`?`), and tilde paths (`~/…`) have a non-command first token and
  route to the server as local sources.
- **Playback = `afplay`** (macOS-only): pause **SIGKILLs** the afplay process
  and records the elapsed position; resume restarts afplay from that position via
  the same WAV-slice mechanism seek uses (`restartAt`). ⚠ The old
  SIGSTOP/SIGCONT approach was removed — it caused CoreAudio buffer bleed (~0.5 s
  of repeated audio on resume) and audible pops during rapid toggling.
  Elapsed time is wall-clock-tracked.
  Plays the server-written WAV directly when the file is on this machine —
  `resolveWav` checks `<config.audio_dir>/<fname>` (the `audio_dir` the server
  reports in its config) and falls back to downloading from `/audio` into
  `~/.readback/cli-cache/` (a CLI-only cache, deliberately NOT the server's audio
  dir). ⚠ The old hardcoded `~/.readback/reader/` path is gone — never reintroduce
  it; the audio location is config-driven now.
- **Seek (←/→ ±5 s)** despite afplay having no transport: `player.ts` parses
  the WAV's RIFF chunks, slices the PCM data at the target byte offset into
  `$TMPDIR/readback-seek-<pid>.wav`, and relaunches afplay there. Rapid
  presses debounce (180 ms) into one jump; a generation counter invalidates
  superseded exits. Seeking from paused/finished resumes playback.
- **Synced transcript** (`PlayerView`): Summary-mode transcript highlights
  word by word in blue. No word timestamps exist — each word gets duration
  proportional to its char count. ⚠ The component wraps text **itself** (one
  `<Text>` per line): ink's `wrap="wrap"` drops ANSI state when a color
  boundary crosses a line break.
- **Resize repaint** (`index.tsx`): a `prependListener("resize")` runs before
  ink's own resize handler — `ink.clear()` + screen wipe so ink repaints on a
  blank slate. Without it, re-wrapped old frames make ink erase the wrong
  number of lines and stale banners stack up. (Alt-screen was tried and is
  glitchier in Warp; don't reintroduce it.)
- **Standalone binary** (`install.sh`): `bun build --compile` →
  `~/.local/bin/readback-cli`. The repo root is baked in via
  `--define process.env.READBACK_ROOT` because `import.meta.dir` is virtual
  inside a compiled binary (`server.ts` falls back to it in dev).
  `react-devtools-core` is a bundled devDependency — ink imports it behind a
  runtime `DEV` check the bundler can't eliminate. The binary is named
  `readback-cli` (not `readback`) so the server-lookup fallback
  `Bun.which("readback")` can't spawn the CLI itself.
- **Prefs** (voice/mode/model/visionModel) persist to `~/.readback/cli.json`. Theme = the
  Ghost palette (#f0f0f0 primary, #808080 dim, #ff5d5d errors/cancel —
  inherited from the deleted web UI)
  plus CLI-only fit colors (#5dd17a green / #e6c35a yellow, `/model` list only)
  and an Xcode-blue accent (#4da3ff: wordmark "BACK", version, caret,
  progress fills, transcript highlight). Banner = half-block wordmark in
  `Header.tsx`; tagline + hints render on the input screen only.

### Read library & dashboard (`library.py`, `src/dashboard/`)

- **`Library`** (`library.py`): stdlib `sqlite3`, no ORM, no new dependency. One
  `reads` table keyed by the WAV's uuid stem (`id`); columns: `title, summary,
  excerpt, source_url, mode, voice, duration_sec, word_count, audio_filename,
  audio_path, created_at, llm_model`. **Connections are opened per call** (`_connect`) so
  it's safe across asyncio's threadpool — every call site wraps it in
  `asyncio.to_thread`. `CREATE TABLE IF NOT EXISTS` on init (idempotent);
  `llm_model` is auto-migrated on existing DBs via `ALTER TABLE ADD COLUMN`.
  `delete()` returns the `audio_path` so the server can unlink the WAV.
  `find_cached(source_url, mode, voice, llm_model)` → the most recent matching
  read (or None if no match / WAV deleted). Backed by composite index
  `idx_reads_cache`.
- `add()` is `INSERT OR REPLACE` (re-reads with the same id overwrite). `list()`
  search is `LIKE %q%` over title/summary/excerpt/source_url; sort is
  `created_at ASC|DESC`.
- **Dashboard** (`src/dashboard/`): Vue 3 + Vite + TS, built with **Bun**
  (`bun run build` → `dist/`, ~28 KB gz). A pure REST + static client — no WS,
  no Python at read time. One shared `<audio>` element (single read plays at a
  time); the active card expands into a **full player** — seekable bar
  (click-to-seek), `elapsed / total`, ±5 s skip buttons, pause/resume/replay,
  and **space / ←→ keyboard parity** with the CLI (ignored while the search box
  is focused). Debounced search (220 ms); delete is confirm-then-fire.
  **Paginated** (`PAGE_SIZE` 20): the list loads page 1 and a "Load more (N)"
  button appends the next page (`offset = reads.length`); the count shows
  "showing X of N". Search/sort reset to page 1; delete decrements `total`.
- **Synced transcript = CLI parity** (`ReadCard`): a *playing Summary* read shows
  its summary with word-by-word **accent-blue highlight**, timed exactly like
  `cli/.../PlayerView.tsx` — no per-word timestamps exist, so each word's share
  of the duration is **proportional to its char count** (`target =
  elapsed/total × totalCharWeight`; a word goes blue once its cumulative weight
  passes `target`). Web wrapping is CSS, so no manual line-splitting is needed
  (the CLI splits by hand only to dodge an ink ANSI-reset bug). Palette + fonts
  (IBM Plex Mono / Martian Mono) lifted from `src/landing-page/style.css` — visually matches
  the CLI + landing page. ⚠ Audio lives only on the Mac; the DB stores the
  absolute `audio_path` so the Pi host can unlink WAVs on delete — `scripts/sync-pi.sh`
  pushes WAVs + DB to Pi; audio is served from Pi's local copy.
- **Motion** (`styles.css` + `App.vue` + `ReadCard.vue`): curves per the
  `emil-design-eng` skill — `--ease-out: cubic-bezier(0.23,1,0.32,1)` for
  entrances/press, `--ease-drawer: cubic-bezier(0.32,0.72,0,1)` for the accordion.
  No bounce/spring in functional UI. Cards enter via
  `<TransitionGroup name="card" appear>` — staggered fade/slide-up (~280 ms) keyed
  by a per-card `--i` (set inline in `App.vue`, **capped at 8** so a 20-card page
  doesn't drag); delete is the `card-leave` (fade + slide-left, `position:
  absolute` so survivors slide up via `.card-move`). The active card's player is a
  `<Transition name="player">` over a `.player-panel` that animates
  **`grid-template-rows: 0fr↔1fr`** (real-height accordion, no `max-height`
  guess); ⚠ this needs the inner `.player` to `overflow:hidden; min-height:0` and
  its top spacing as **`padding-top`, not `margin-top`** (margins aren't clipped by
  the collapse). Buttons get a `:active { scale }` press. ⚠ `prefers-reduced-motion`
  is **gentle, not zero** — keeps opacity fades (card fade, loading pulse, caret),
  drops only movement (slide, accordion height, press scale).

## Things that look like bugs but aren't

- **First synth is slow.** One-time CSM graph warm-up + ~6 GB checkpoint download
  on first ever run; `load()` pre-warms but the first real synth still pays some
  compile cost.
- **Summary mode has no first-token streaming.** Summary is a single `oneshot`
  call — the whole summary is produced, then synthesized. (Full mode skips the
  LLM entirely.)
- **Speed has no effect.** `tts.csm.speed` is inert — CSM has no speed control.
- **Clone sounds garbled.** Almost always a `ref_text` that doesn't match the
  clip, or a too-short reference at low temperature. Fix the transcript / use a
  5–8 s clip / raise temperature toward 0.6–0.8.
- **Brief silence on resume.** Pause kills afplay and resume restarts it from a
  sliced WAV (~50 ms). This is intentional — the old SIGSTOP/SIGCONT was faster
  but caused audible buffer bleed (0.5 s of repeated audio).
- **Untagged reasoning IS emitted by Qwen3.5-9B-4bit** (corrects an earlier
  claim that it's "clean"). Left unchecked it writes a plain-text "Thinking
  Process:" preamble with no `<think>` tags, so `_ThinkStripper` can't catch it.
  The fix is `enable_thinking=False` on the chat template (see LLM section) — NOT
  the stripper, which only handles tagged `<think>…</think>`.

## Install & verification

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .                          # csm-mlx + mlx-lm + mlx-vlm pulled automatically
readback                                  # starts the server (or: python -m readback)
cd src/cli && bun run start                   # terminal CLI from source (auto-spawns the server)
cd src/cli && ./install.sh                    # or: standalone binary → ~/.local/bin/readback-cli
```

Smoke test: paste an article URL → Full mode → player appears, audio plays,
download works. Summary mode → transcript toggle shows the spoken summary. CLI:
`bun run start` with no server running → it spawns one, a pasted URL reads and
plays via afplay, q exits and the spawned server dies. Voice
work: `Synthesizer(Config.load().tts).synthesize("…")` from a Python REPL.

## Version

Current: **v4.1.0** — audio quality + performance. Read cache skips the entire
pipeline on re-reads (keyed by url/mode/voice/llm_model). Degenerate-chunk
guard retries all-silence synthesis once. Light crossfade (100 ms fade-out) at
chunk joins. New `llm_model` column in the reads table (auto-migrated).

Previously: v4.0.0 — full MLX LLM stack (Ollama removed); v3.0.0–v3.7.0 (see
memory `version-history` for full changelog).
Set in `pyproject.toml`, `src/readback/__init__.py`,
`src/cli/package.json`, and `src/dashboard/package.json` — bump all four when
releasing. The standalone CLI binary needs `src/cli/install.sh` re-run to pick
up the new version in its banner.
