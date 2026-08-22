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
- **MLX/Metal (20-core GPU)** runs CSM-1B TTS + the LLM — text via mlx-lm, OCR via
  mlx-vlm on the SAME weights — all in-process.
- **MLX is not multi-thread safe** — its default GPU stream binds to the thread
  that first touches the device, so `CsmEngine` owns a single-thread executor and
  runs all model work on it (see TTS section).

## Stack

- **Extraction**: `trafilatura` (URL → clean article text) + a browser-UA urllib
  fallback for sites that 403 the default agent. Local images (`.png/.jpg/.heic/…`)
  → mlx-vlm OCR on `cfg.llm.model`. Folder or glob → multi-page
  mode: pages OCR'd in natural-filename order and stitched into one continuous
  Article (a scanned page is a page, not a chapter — no synthetic headers), then
  summarized/read like any article.
 - **LLM**: **mlx-lm** (in-process on MLX/Metal), default
  **`mlx-community/Qwen3.5-9B-4bit`** (chain-of-thought disabled via
  `enable_thinking=False`; `<think>` stripping as backup — see LLM section). Used
  by Summary mode (`LLMClient.oneshot`), title generation, **and image/book OCR**
  (via mlx-vlm — same HF id, separate loader). ⚠ There is **no separate OCR
  model**: Qwen3.5 is a VLM (`model_type: qwen3_5` + a `vision_config`, and
  mlx-vlm ships a `qwen3_5` handler), so the old `ocr:` block was a redundant
  ~5.6 GB download. A text-only `/model` pick disables image/book reads.
  `/model` can switch per-read; any downloaded MLX chat model works.
- **TTS**: **CSM-1B** (`senstella/csm-1b-mlx`, Sesame Conversational Speech Model)
  via **`csm-mlx`** on Metal, bf16, 24 kHz native. 2 built-in
  reading voices + clone-condition voices + optional LoRA fine-tuning. English-best.
- **Server**: FastAPI + WebSocket (`/ws`) for live reads, plus a small REST
  surface (config / models / read-library). Two clients: the terminal CLI (the
  sole `/ws` consumer) and the web dashboard (REST + static, served at `/`).
- **Terminal CLI**: Bun + TypeScript + Ink (React for CLIs) in `src/cli/` — the sole
  client of the `/ws` protocol; `afplay` playback, macOS-only.

## Project Structure

```
readback/
├── pyproject.toml             # v4.4.0; csm-mlx (git dep) + mlx-lm + mlx-vlm + trafilatura + fastapi
├── config.example.yaml        # the TEMPLATE that ships in git: llm / tts.csm / reader blocks
├── config.yaml                # ⚠ GITIGNORED — the user's own copy (setup.sh cp's the
│                              # example on first run and never overwrites it).
│                              # Config.load() falls back to config.example.yaml when
│                              # config.yaml is absent, so a fresh clone runs unchanged.
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
├── tests/                     # 79 pytest cases — PURE LOGIC only (no MLX/CSM/GPU): chunking,
│                              # silence-tidy, fade-out, extract scrub, library + cache, think-stripper,
│                              # tones, map-reduce batching, summary trim, batched-synth
│                              # drive loop (order/progress/cancel/retry/fallback),
│                              # feed parsing (RSS/Atom, autodiscovery, index scrape,
│                              # pick round-robin).
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
    │                          # BusyView,PlayerView,ModelList,LibraryView,HelpView}.tsx
    └── readback/              # python package (src layout; wheel packages src/readback)
        ├── __main__.py        # `readback` CLI: argparse --host/--port/--model/--config, uvicorn boot
        ├── config.py          # Pydantic config: LLMConfig / CsmTTSConfig
        │                      # (+ CsmVoicePrompt) / ReaderConfig; load() resolves clone wav +
        │                      # lora + library_db; stale llm.vision_model / ocr: keys are ignored
        ├── library.py         # SQLite read library (stdlib sqlite3): Library class
        │                      # (add/list/get/delete/find_cached over a `reads` table) — powers
        │                      # the dashboard + the read cache
        ├── llm/
        │   ├── client.py      # LLMClient.oneshot() for summary + the <think> stripper
        │   └── models.py      # MLX model listing (HF cache scan) + RAM-fit verdict (GET /api/models)
        ├── pipeline/
        │   ├── extract.py     # fetch_article (URL/image) + fetch_multi_page (folder/glob);
        │   │                  # trafilatura + UA fallback; mlx-vlm OCR on cfg.llm.model; TTS-prep scrub
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
  llm_model, recipe)` checks for an existing WAV matching the exact cache key. On hit the
  entire pipeline is skipped — `done` fires immediately with the cached record.
  The cache key includes the LLM model so a `/model` switch doesn't replay stale
  audio, **and `pipeline.RECIPE_VERSION`** so a change to the summary prompt,
  chunking/pausing, or synthesis re-renders instead of replaying audio the OLD
  code produced. ⚠ **Bump `RECIPE_VERSION` with any such change** — otherwise
  you re-read an article to check a quality fix and hear the very output you
  just fixed. Pre-migration rows carry `recipe = ''` and never match. The lookup is backed by a composite index (`idx_reads_cache`). A hit
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
  uuid stem. `llm_model` stores the summary LLM used, `recipe` the
  `RECIPE_VERSION` that produced the audio (both part of the cache key).
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
  `_ocr_via_mlx` (mlx-vlm, model = `cfg.llm.model` — the summary model does OCR
  too). sips converts HEIC/TIFF/BMP/WebP → JPEG, and **also any image with an
  alpha channel** (`_has_alpha`): ⚠ mlx-vlm flattens alpha onto BLACK, so a
  transparent PNG of black text arrives as a solid black rectangle and OCR
  returns confident garbage (`$$\frac{1}{2}$$`) instead of erroring — sips
  flattens onto white. `_image_to_jpeg` returns the temp file's **path** (mlx-vlm
  takes paths); don't reintroduce a bytes round-trip. **Multi-page** (`_is_multi_page` → folder or
  glob): `_collect_images` natural-sorts by filename, `fetch_multi_page` OCRs each
  page (the vision model is loaded once and cached across calls) and joins
  the pages with a single space at each seam (a book sentence runs across page
  breaks; within-page paragraphs survive). Returns one continuous Article — the
  server then summarizes/reads it through the **same** step 2 as a URL article (no
  special-casing; long scans are map-reduced by `summarize_article`, not truncated).
  Progress fires `reading page N / M` via the existing `phase` WS channel.
- **Tones** (`tones.py`): a `Tone` bundles a summary framing prompt + a CSM
  *base* delivery `temperature` (per-chunk `_expressive_temperature` in
  `speak.py` nudges it around this base — see Chunk + synth below).
  `classify_source(src)` (⚠ defined in `extract.py`, not `tones.py`) → `"book"`
  (image / folder / glob)
  or `"article"` (URL); `tone_for(kind)` → `BOOK` (measured, **0.6**, opens by
  naming the chapter/topic) or `ARTICLE` (livelier explainer, **0.8**). Auto,
  server-side, invisible to the CLI — **no `/tone` override or config yet** (room
  for a 3rd tone). Both `summary_system` prompts carry a **hard 250-word
  (10–15 sentence) length ceiling** so the spoken summary stays a briefing, not a
  retelling (paired with `oneshot`'s `max_tokens` bound). ⚠ The ceiling alone let
  the model pad short sources with generic, ungrounded wrap-up sentences to
  approach 250 words regardless of how little the source actually said —
  `_summarize_once` (`summarize.py`) now spells out the source's **word count**
  in the user prompt, and both prompts explicitly frame 250 as a ceiling to
  reserve for long sources, targeting roughly half the source's word count
  otherwise; forbids wrap-up sentences not grounded in a specific source fact,
  tells the model to skip the source's own housekeeping (acknowledgements,
  thanks, calls to action — faithful but zero-information for a listener),
  and asks for natural spoken rhythm (varied sentence length, emphasis on a
  genuinely notable point) instead of a flat, even-register list of facts.
  The shared length policy lives ONCE, in `_LENGTH_RULES` (+ `_PLAIN_PROSE_RULE`),
  `.format`-ed into both prompts — edit it there, not in the prompt bodies.
  ⚠ `_PLAIN_PROSE_RULE` asks for **2-4 short paragraphs** — that is a DELIVERY
  setting, not cosmetics: `speak.py` takes each pause's length from the
  paragraph breaks (`chunk_spans` → `_gap_for`). The old "plain flowing
  sentences" wording returned ONE unbroken block every time (measured 220 words,
  zero newlines), so a Summary read had no structural pauses at all. The
  ceiling itself is `SUMMARY_WORD_CEILING` (250), exported because the prompt is
  only advisory: `summarize_article` **hard-enforces it post-hoc** with a
  sentence-boundary trim (`_trim_to_word_ceiling` — the model measured 313 words
  from a 3,446-word source on prompt alone).
  Tone shifts *delivery temperature*, NOT the voice — the user's
  `/voice` is untouched. Book sources also take their **title from the first ~3 OCR
  lines** (`_book_title_from_text`), which the BOOK prompt then leads with.
- **Summarize** (`summarize.py`): short body (≤ `reader.summary_max_chars`, default
  **60000** — Qwen3.5-9B's 262K-token context comfortably single-passes articles
  up to this size; the old 16000 default forced most long-form articles through
  map-reduce for no reason) → one `oneshot` with the spoken-explanation prompt
  (`_summarize_once`). The framing prompt is the tone's `system` (passed by the
  server; defaults to the article tone).
  Longer input (book scans) → **map-reduce** (`_map_reduce`): `_batches` packs the
  text into ≤`max_chars` batches (paragraph → sentence → hard-cut; ⚠ `_PARA_SPLIT`
  is `\n+`, NOT `\n{2,}` — trafilatura emits each paragraph as a SINGLE line, so
  a blank-line split matched nothing and every source silently fell through to
  sentence-level packing), each condensed
  with `_MAP_SYSTEM`, the digests joined and reduced via `_summarize_once`;
  recurses (depth ≤ 3) if the joined digests still overflow. ⚠ This **replaced** the
  old hard truncation that silently dropped everything past ~10-12 pages. Optional
  `progress(done, total)` fires per batch in the map phase (server → `summarizing
  section N / M`). Returns the article text unchanged if the LLM produced nothing.
  ⚠ The **original source's word count rides through map-reduce** as
  `source_words` — the reduce step's `body` is the compressed digests, and
  anchoring the prompt's length target to *their* count mis-calibrates exactly
  the long inputs map-reduce exists for. Non-empty summaries are then clipped by
  `_trim_to_word_ceiling` (sentence-boundary cut at `SUMMARY_WORD_CEILING`,
  always keeps ≥1 sentence, ⚠ **and preserves paragraph breaks** — it used to
  `" ".join()` the sentences, silently reflowing every summary into one line and
  destroying the very breaks the pauses are derived from) — the code-level backstop for the prompt's HARD
  LIMIT, which also caps synthesis time (every overshoot word is paid for again
  in TTS).
- **Chunk + synth** (`speak.py`):
  - `chunk_text` — paragraph-respecting, sentence-aware merge; **each chunk's cap
    is randomized** (`_next_chunk_cap`) between `_MIN_CHUNK_CHARS` (**280**) and
    `_MAX_CHARS` (**400**) instead of always hitting the same fixed cap — a
    uniform cap gives every chunk the same length, which reads with a
    mechanical, same-every-time breath cadence; randomizing it per chunk (same
    input text produces a different chunk count/boundaries run to run — verified)
    varies pacing AND gives `_expressive_temperature` below more chances to land
    a short cap on a single sentence instead of merging it with a
    differently-toned neighbor. ⚠ **DON'T narrow this band for "finer
    expression".** It was tried — batching made small chunks cheap, so the band
    was moved to [120, 200] to give `_expressive_temperature` a per-sentence
    window. It sounded WORSE: delivery shifted tone every sentence or two instead
    of settling ("audio is not stable, tone keeps changing"), and it was
    reverted. Chunk size is a DELIVERY setting; speed comes from
    `tts.csm.batch_size`, which doesn't change how text is divided.
    ⚠ `chunk_text` splits on EVERY `\n`, so hard-wrapped test fixtures produce one
    chunk per LINE and silently defeat band changes — measure with real article
    prose (trafilatura emits paragraphs as single lines).
    ⚠ Measured drift metrics (per-chunk pitch sd, loudness sd) did NOT separate
    good reads from bad here — a reference-quality read scored 23.0 Hz sd vs 22.4
    for a read the user rejected. Judge delivery changes BY EAR.
    The over-long-sentence safety net (comma split, then a
    space-level `_hard_split` for comma-free runs) measures against the fixed
    `_MAX_CHARS`, not the random per-chunk cap. Sub-`_MIN_CHARS` (8) fragments
    are stitched onto a neighbor — mid-paragraph they're carried into the next
    piece (⚠ never silently dropped; a low random cap made drops reachable —
    "Wow!" was lost in ~21% of runs pre-fix, `test_short_fragment_is_never_dropped`
    guards it).
  - `_tidy_silence` — ⚠ **this is what removes the halting feel.** CSM, conditioned
    on the casual/disfluent Sesame prompt, emits long mid-utterance pauses;
    `_tidy_silence` trims leading/trailing silence (−40 dB threshold) and caps any
    internal silent run to `max_pause_ms` (300). Model-agnostic post-processing.
  - `_expressive_temperature` — ⚠ **the only expression-varies-with-content knob
    CSM exposes.** CSM has no direct emotion/prosody API; sampling temperature
    (more variation in pitch/pacing at higher values) is the one delivery lever
    it has, so this nudges the tone's *base* temperature per chunk from its
    punctuation: `!` → +0.08 (emphatic), `?` → +0.04 (questioning), ≥3 commas and
    no `!`/`?` → −0.03 (dense/measured), clamped to `[0.55, 0.95]` (below ~0.55 a
    short clone reference destabilizes). Granularity is **per chunk, not per
    sentence** — at the [280, 400] band a chunk spans a few sentences and gets
    whichever punctuation rule matches first. ⚠ That coarseness is DELIBERATE:
    making the window per-sentence (the [120, 200] band) shifted tone too often
    and sounded unstable. ⚠ In the batched path each row carries its own
    temperature via `_make_batch_sampler` — batching does NOT flatten delivery.
    See the speed/quality guide in `config.yaml`.
  - `synthesize_article` — **batched by default** (`_synthesize_batched`): chunks
    go to `synth.synthesize_batch` in groups of `tts.csm.batch_size` (8), each
    row carrying its OWN `_expressive_temperature`, then tidy → fade-out tail →
    join with `reader.gap_sec` (0.18 s) gaps. Measured **~2x** on synthesis
    at the shipped [280, 400] band (61.3 s → 28.6 s on the same summary), and it
    does NOT change how the text is divided. Falls back to the old
    sequential loop when the engine has no `synthesize_batch`, `batch_size` is 1,
    or the batch path raises — so a csm-mlx upgrade degrades to slow, not broken.
    `progress` still fires once per chunk; `should_stop` is checked **per batch**
    (measured cancel latency 8.0 s, better than the old per-chunk latency at the
    old band). **Degenerate-chunk guard:** rows whose tidied audio is empty are
    collected and retried once in a follow-up batch.
  - `_length_buckets` + `_batches` — group chunks for the batch path.
    `_length_buckets` sorts by text length so a batch's rows are near-equal
    (prompts are left-padded to the batch max, and the frame loop runs until
    EVERY row hits EOS, so a short row batched with a long one just idles). Since
    the pads are masked out of attention, this is now purely a work saving — it
    is no longer load-bearing for quality.
    ⚠ `_batches` **evens the groups out** — 11 chunks at size 8 is 6+5, never
    8+3: a batch's cost is nearly flat in batch size, so a 3-row tail batch costs
    about as much as a full one (measured RTF 0.33 for 8+3 vs 0.26 for 6+5).
    Grouping is by index, so document order is unaffected.
  - `_gap_for` + `chunk_spans` — ⚠ **the pause follows the TEXT, not a flat
    constant.** `chunk_spans` returns each chunk paired with *does it end a
    paragraph*, and the join takes its length from that: a paragraph end is real
    structure the author wrote (`_PARA_GAP_SCALE` **2.0**), while a mid-paragraph
    join is an ARTIFACT of the random chunk cap splitting a running sentence, so
    it carries on (`_MID_GAP_SCALE` **0.6**). Both are multiples of
    `reader.gap_sec` (0.18), which still moves the whole read's pacing. Impact is
    concentrated in Full mode / book reads: an 8-paragraph article goes 1.44 s →
    2.88 s of join silence, while a Summary (the LLM emits ONE paragraph) barely
    moves — 0.90 s → 0.79 s, i.e. slightly tighter. `chunk_text` is the
    plain-text view of `chunk_spans` for callers that only need the strings.
  - `_fade_out_tail` — 100 ms linear fade-out on each chunk's tail before the
    silence gap, smoothing the voiced→silence transition (no hard cut → click).
  - `_peak_normalize` — ⚠ **levels every voice to the same loudness.** CSM matches
    the energy of its reference clip, so clone voices (quiet refs) came out ~18 dB
    softer than the near-full-scale built-in prompts. The concatenated buffer is
    peak-normalized to **0.95** before return (no limiter — CSM output has no stray
    transients). Applied unconditionally; clean speech so it's safe.

### Feed picks (`pipeline/feeds.py`, `GET /api/feed`, `cli/.../PickList.tsx`)

- **What it is**: the sites in `reader.feeds` are crawled for their newest posts
  and listed as numbered picks on the CLI's input screen; `1`–`N` reads one
  immediately. Stdlib only (`urllib` + `xml.etree` + regex) — no new dependency.
- **Two-tier discovery** (`fetch_source`): ⚠ half of modern blogs ship no RSS.
  1. the source URL is fetched once; if it IS a feed (`<?xml` / `<rss`) it's
     parsed directly; 2. otherwise autodiscovery on the HTML
     (`discover_feed_url`) then the conventional paths (`_FEED_PATHS`);
  3. else `scrape_index_links` on the index HTML.
  ⚠ `discover_feed_url` matches on `type=application/(rss|atom)+xml`, **not on
  `rel="alternate"` alone** — `rel=alternate` is also how sites declare
  translations (claude.com lists a dozen hreflang alternates), and following one
  fetches a localized HTML page that parses to zero items.
- **`scrape_index_links`** keeps only links one level below the index's own path
  (`/blog/` → `/blog/post`, not `/blog/tag/x`, not `/pricing`), deduped, in
  document order — a blog index lists newest first, so document order IS recency
  and these items carry **no `published`**. ⚠ Anchor text is usually a "Read
  more" button (`_GENERIC_ANCHOR`), so titles come from the slug
  (`title_from_slug`).
- **`interleave` is round-robin, not a global date sort** — a site that posts
  daily would otherwise own every slot, and the point of the list is what's new
  *across* the sites. Round 1 = each source's newest (dated newest-first among
  themselves, undated last), round 2 = each source's second-newest, …
- **Already-read posts retire from the list.** `/api/feed` filters the pool
  against `library.read_urls()` and backfills from the rest of the crawl, so
  finishing a pick promotes the next post instead of leaving a stale suggestion
  (or a shorter list). The CLI re-asks for picks on every `done` — no `refresh`
  flag, since the crawl is cached and only the filter changed. ⚠ Matching is on
  `feeds.pick_key` (scheme+host+path, **query stripped**): a Medium feed hands
  out `?source=rss----…` while the library stores whatever was read, so a raw
  string compare would mark that post unread forever.
- **`FeedCache`** (held by `create_app`) caches for `reader.feed_ttl_sec` (900)
  so CLI launch is instant after the first crawl (~7 s over three sites). It
  keeps the WHOLE crawl (`pool()`, `POOL` = 30), not just the displayed N — the
  read-filter above needs spares to backfill from. `/api/feed?refresh=1` (the
  CLI's `/feed`) always re-crawls. A source that
  fails contributes nothing — picks degrade, they never error.
- **Reads are forced to Summary mode** (`handlePick` in `app.tsx`) regardless of
  the current `/mode`: the user picked a headline off a briefing list, not a
  document they asked to hear in full. `BusyView` takes the pick's `title` so the
  spinner isn't anonymous (there's no URL on screen to read).

### TTS — CSM-1B (`tts/csm_engine.py`, `tts/synthesizer.py`)

- **Engine: `csm-mlx`** (`senstella/csm-1b-mlx`, `ckpt.safetensors`). float32 @
  24 kHz, cast to **bf16** by default (`cfg.precision`: `bf16`/`fp16`/`fp32`).
  bf16 is ~6% faster than fp32 with no audible quality loss at normal
  listening; switch to `fp32` for max fidelity if bf16 ever sounds off on a
  clone voice. `_make_sampler` caches per
  `(temperature, top_k)` to avoid recreation per chunk.
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
- **`synthesize_batch(items)` is the throughput path** — ⚠ the single biggest
  speed knob in the project. CSM emits one frame per 80 ms of audio and each frame
  is 1 backbone step + 31 *sequential* decoder steps on a 1B model (~400 tiny
  matmuls per audio-second), so it is **launch-latency bound, not compute bound**
  and the GPU idles at batch 1. Measured (ms/frame → audio per wall-second):
  1 → 51.6/1.55 · 2 → 80.5/1.99 · 4 → 82.1/3.90 · 8 → 84.8/**7.55** — 8x the work
  for 1.64x the time. `_synthesize_batch_impl` mirrors `csm_mlx.generation.generate`
  over the batch dim `generate_frame` already supports: prompts are
  `ref ++ text` tokens **left-padded** to the batch max, one
  `make_prompt_cache`, per-row EOS tracking, then `decode_audio` per
  row. ⚠ It therefore leans on csm-mlx internals — `speak.py` falls back to the
  sequential path if it raises. `_ref_tokens_for` caches the tokenized reference
  per voice (csm-mlx re-runs that Mimi encode, ~0.03 s, on every `generate`).
- ⚠ **The pads MUST be masked out of attention (`_pad_key_mask` /
  `_prefill_mask`) — this is what fixed the muffled voice.** `token_mask` only
  zeroes the pad *embeddings*; it does not stop real tokens from *attending* to
  those positions. A zero embedding stays exactly zero through every layer
  (RMSNorm(0)=0, no biases), so each pad is a key of 0 scoring q·0 = 0 — weight
  exp(0)=1 in every softmax denominator against a value of 0. The pads act as a
  bank of neutral sinks that dilute attention and flatten the output
  distribution; measured on a 236-frame prompt, codebook-0 top-1 probability fell
  0.193 → 0.049 at 8 pads (KL 0.72) and → 0.023 at 32 (KL 1.49). Flatter
  distribution → noisier acoustic tokens → the soft, MUFFLED read that parked
  this branch. With the mask, KL vs the unpadded prompt is ~0.0002 (bf16 noise),
  i.e. batching is again a pure throughput change. Because
  `LlamaModel.__call__` builds its own causal mask and accepts no mask argument,
  `_frame_impl` drives the backbone layer by layer — a masked twin of
  `generate_frame` (the decoder needs no mask: its per-frame inputs are 1-2
  positions and never padded). ⚠ `_prefill_mask` force-enables the **diagonal**:
  a pad query has no valid key at or before it, and a fully-masked softmax row
  returns NaN that would poison the batch through the next layer's K/V. A
  same-length batch skips the mask entirely and runs the original path.
  ⚠ **Don't raise `batch_size` much past 8**: the loop runs until EVERY row hits
  EOS, so one runaway row stalls the batch (16 measured RTF 0.17 and 0.37 on
  consecutive runs; 8 measured 0.23 twice).
- `_make_batch_sampler(temps)` — per-ROW sampling temperature, shape `(B, 1)`.
  Mirrors mlx_lm's chain (`apply_top_k` then `categorical_sampling`, both
  last-axis ops) so each chunk keeps its own `_expressive_temperature` inside a
  shared batch. Without it, batching would flatten delivery across the batch.
- One-chunk `synthesize` remains as the fallback path; offline reads get no
  benefit from token streaming, so the csm-mlx `stream_generate` path was removed.
- ⚠ **One engine per process.** `csm_mlx.generation` creates its `default_stream`
  at import time, bound to whichever thread imported it — the executor thread of
  the FIRST engine. A second `Synthesizer` in the same process gets a second
  executor and dies with "no Stream(gpu, 0) in current thread". Benchmarks that
  A/B two configs must fork a process per config.

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

- `LLMConfig{model}` (`llm:`) — the ONE HuggingFace ID: mlx-lm for summary +
  title gen, mlx-vlm for image / book-scan OCR. ⚠ The separate `OcrConfig`
  (`ocr:` block) and the `vision_model` / `current_vision` wire fields were
  **removed** — one model does both. Old configs still load: `llm.vision_model`
  falls to pydantic's `extra="ignore"`, an `ocr:` block to `Config.load()`'s
  unknown-top-level-key drop. Neither is migrated; nothing reads them.
- `CsmTTSConfig{precision, speaker, temperature, top_k, max_audio_length_ms,
  ref_max_sec, batch_size, voices, lora_path}`. `batch_size` (**8**) is how many
  chunks ride one CSM frame loop — the main speed knob (see TTS section); 1
  restores the sequential path. The checkpoint (`senstella/csm-1b-mlx`) is
  fixed in the engine.
- `ReaderConfig{output_dir, default_mode, gap_sec, summary_max_chars,
  library_db, feeds, feed_picks, feed_ttl_sec}`. `feeds` is a list of
  `FeedSource{url, name?}`; a `field_validator(mode="before")` accepts bare URL
  strings too, so `feeds: ["https://…"]` is valid YAML. `feed_picks` (5) is how
  many picks the CLI shows and keys. `output_dir` + `library_db` default to a sibling
  `readback-audio-db/` folder next to the repo (`../readback-audio-db/audio` and
  `../readback-audio-db/library.db`) — audio + DB in one visible, back-up-able
  place, NOT a hidden `~/.readback` dir. ⚠ Defaults use **`../` relative
  notation** (no personal absolute path baked into the public repo).
- ⚠ **`config.yaml` is gitignored**; `config.example.yaml` is the checked-in
  template. `Config.load()` falls back to `config.example.yaml` when
  `config.yaml` is missing (a fresh clone, or a run before `scripts/setup.sh`) —
  bare defaults would silently drop the shipped clone voice, feeds, and reader
  paths. `setup.sh` step 3b copies example → `config.yaml` and NEVER overwrites
  an existing one. ⚠ Add a new key to BOTH files.
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
- `llm/models.py` (`GET /api/models` + the `read` message's `model` field):
  scans downloaded MLX models in the HuggingFace cache with a RAM-fit
  verdict (need ≈ size×1.2+1 GiB; good ≤50% / tight ≤75% of total RAM via
  `sysctl hw.memsize`) and recommends the largest good-fit model. ⚠
  **Vision-ONLY** checkpoints (`_VISION_MARKERS` — `VL`/`vision`/`vlm`) are
  filtered OUT: the listed model must drive Summary mode through mlx-lm, which a
  VL-only checkpoint can't. A dual-capable model (Qwen3.5) isn't matched by those
  markers, so it stays listed. A per-read `model` mutates `cfg.llm.model` in
  place (process-wide, like `swap_voice`; **not** written back to `config.yaml`)
  — the LLM client and the vision loader each detect the change and reload on
  next use (`oneshot()` / `_ocr_via_mlx`).

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
  the spawned server. `readbackBin()` prefers `.venv/bin/python3 -m readback`
  (works without venv activation), falls back to `.venv/bin/readback`, then
  `which readback`. Stderr is captured — startup crashes show the last 5 lines.
- **Ink screen model** (`app.tsx`): `useReducer` switches one mounted screen
  (`input` | `busy` | `player` | `library` | `quitting`), so key handlers only
  land on the active screen. Slash commands: `/voice`, `/mode`, `/model` (lists
  downloaded MLX models via `GET /api/models` with a RAM-fit verdict +
  recommendation, switches the LLM per-read — it serves Summary mode AND
  image/book OCR, so there is no second picker; `/vision` was removed along with
  the separate OCR model), `/speed [x]` (playback rate 0.5–2,
  persisted; no server involvement — see Playback speed below), `/feed`
  (re-crawls the picks via `/api/feed?refresh=1`; the arriving list clears the
  "refreshing…" notice), `/library` (alias `/lib` —
  `GET /api/library?sort=newest&limit=20&offset=N`, arrow-key nav, `space` to
  preview inline (plays audio without leaving the library; shows `♫` + elapsed;
  space again stops), Enter to open the full player, `d` twice to delete),
  `/help`, `/quit`; esc cancels a read. Every library row shows
  `mode · duration · words · date` inline (active row in accent blue).
  `q` when the URL input field is empty triggers quit — intercepted in
  `UrlInput.onChange` before the controlled value updates. **Digits `1`–`9` are
  intercepted the same way** (empty field only, bounded by `pickCount`) and read
  that numbered pick; a digit inside a URL or path types normally because the
  field isn't empty by then. Quit path:
  `dispatch("quitting")` → braille spinner renders for 300 ms → `shutdown()` +
  `exit()` (the delay lets Ink paint one frame before tearing down).
  **Input guard** (`handleSubmit`): an input is a command iff its FIRST token is
  a known command word (`KNOWN_COMMANDS`, kept in sync with `handleCommand`'s
  switch). ⚠ Match on the first token only — the arg may contain a `/` (e.g.
  `/model mlx-community/Qwen…`), so the old "no second `/`" heuristic wrongly
  routed `/model <hf-id>` to the read pipeline. Absolute paths (`/Users/…`),
  globs (`*`/`?`), and tilde paths (`~/…`) have a non-command first token and
  route to the server as local sources.
- **Playback speed** (`player.ts` `setRate`, `/speed` + `+`/`-` in the player,
  0.5–2× step 0.1): `afplay -r RATE -q 1` (high-quality **pitch-preserving**
  rate scaling — CSM has no speed control, so pace is playback-side). ⚠ `elapsed`
  tracks **audio position**, advancing at `rate ×` wall time — seek slices and
  the synced transcript depend on this; don't revert the timer to plain wall
  clock. A mid-play rate change restarts afplay at the current position via the
  seek-slice mechanism (debounced like seek). Rate shows next to the progress
  bar when ≠ 1×; persists in prefs (`speed`).
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
  proportional to its char count. The metadata line shows "Xs to generate" for
  live reads (from `timings.total` in `DoneMsg`; hidden for library replays).
  ⚠ The component wraps text **itself** (one `<Text>` per line): ink's
  `wrap="wrap"` drops ANSI state when a color boundary crosses a line break.
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
- **Prefs** (voice/mode/model/speed) persist to `~/.readback/cli.json`. Theme = the
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
  `llm_model` and `recipe` are auto-migrated on existing DBs via `ALTER TABLE ADD
  COLUMN`.
  `delete()` returns the `audio_path` so the server can unlink the WAV.
  `find_cached(source_url, mode, voice, llm_model, recipe)` → the most recent matching
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
- **`tts.csm.speed` has no effect.** It's inert — CSM has no speed control.
  Pace is playback-side: the CLI's `/speed` (afplay `-r`, pitch-preserving).
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

Current: **v4.4.0** — feed picks: the CLI opens on what's new.
`reader.feeds` lists the sites you read; the server crawls them
(`pipeline/feeds.py` — RSS/Atom autodiscovery, then conventional paths, then an
HTML-index scrape for the ~half of blogs that ship no feed) and the CLI shows
the newest posts as numbered picks. `1`–`N` on the empty input reads one in
Summary mode immediately. Picks round-robin the sources (one prolific blog can't
own every slot), are filtered against the read library so a finished pick
retires and the next post is promoted, and are TTL-cached (`/feed` re-crawls).
⚠ Also in this release: **`config.yaml` is now gitignored**, with
`config.example.yaml` as the checked-in template (`setup.sh` copies it;
`Config.load()` falls back to it).

Previously: v4.3.0 — ~2x synthesis, same quality.
Batched CSM synthesis (`tts.csm.batch_size`, default 8): the frame loop is
launch-latency bound, so 8 rows cost 1.64x the time of 1 — measured
61.3 s → 28.6 s synthesizing the same summary. Fixed by masking left-pad
tokens out of attention (`_pad_key_mask`/`_prefill_mask`), which had been
flattening the output distribution (codebook-0 top-1 0.193 → 0.049 at 8 pads)
and causing the muffled voice that stalled this work for weeks; masked, KL vs.
unpadded is ~0.0002 (bf16 noise). Pauses now follow paragraph breaks
(`_gap_for`: 2x at a paragraph end, 0.6x mid-paragraph). Read cache gained
`pipeline.RECIPE_VERSION` so a pipeline change re-renders instead of replaying
stale audio.

Older: v4.2.0 — summary quality + delivery + CLI playback speed
(word-count anchor + 250-word ceiling trim, `_expressive_temperature`,
randomized [280, 400] chunk band, `summary_max_chars` 16K→60K, `/speed`);
v4.1.0 — audio quality + performance (read cache, degenerate-chunk
guard, chunk-join crossfade, `llm_model` column); v4.0.0 — full MLX LLM stack
(Ollama removed); v3.0.0–v3.7.0 (see memory `version-history` for full changelog).
Set in `pyproject.toml`, `src/readback/__init__.py`,
`src/cli/package.json`, and `src/dashboard/package.json` — bump all four when
releasing. The standalone CLI binary needs `src/cli/install.sh` re-run to pick
up the new version in its banner.
