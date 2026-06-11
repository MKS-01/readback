# Architecture — readback (v0.9.0)

How the pieces fit together and why. System-level companion to
[CLAUDE.md](CLAUDE.md) (implementation notes, gotchas, exact knobs) and
[README.md](README.md) (user-facing). When a specific threshold or flag is in
doubt, CLAUDE.md is authoritative.

## 1. What it is

A fully **on-device** article reader served as a web app. You paste a URL; the
server fetches and extracts the article, optionally summarizes it with a local
LLM, synthesizes the whole thing offline with CSM-1B, and hands back an audio
file the browser plays and lets you download. One process, one CLI (`readback`),
one WebSocket. Two clients speak that WebSocket: the browser frontend and an
optional terminal client (`cli/`, Bun + Ink, macOS) that plays the result via
`afplay`.

```
URL ─▶ fetch + extract ─▶ [summary] ─▶ chunk ─▶ TTS (offline) ─▶ WAV ─▶ browser
       (trafilatura)    (Ollama)            (CSM-1B / csm-mlx)
```

Unlike the real-time voice assistant this project began as, synthesis is **batch,
not streaming**: there is no live turn to keep pace with, so the whole piece is
synthesized up front. That removes audio-underrun and echo entirely and lets
voice quality win over latency.

## 2. Process & concurrency model

A single FastAPI app (`readback/web/server.py`). The event loop stays responsive
while a read job runs because all heavy work is pushed off it:

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

## 3. The pipeline (`readback/reader/`)

1. **Extract** (`extract.py`) — `fetch_article(url)` downloads via trafilatura,
   falling back to a browser-UA `urllib` fetch when a site 403s the default
   agent, then `trafilatura.extract(..., favor_precision=True)` pulls the article
   body. Light TTS-prep scrubbing strips URLs, `[12]` citation markers, and
   collapses whitespace so the voice doesn't read markup aloud. Returns an
   `Article{title, text, url}`.
2. **Summarize** (`summarize.py`, Summary mode only) — `summarize_article` calls
   `LLMClient.oneshot(system, user)` with a spoken-explanation system prompt;
   long articles are truncated to `reader.summary_max_chars`. Full mode skips
   this and reads `article.text` verbatim.
3. **Chunk + synthesize** (`speak.py`) — `chunk_text` splits into TTS-sized,
   paragraph-respecting chunks (~280 chars, sentence-aware, over-long sentences
   split on commas). `synthesize_article` synthesizes each chunk fully,
   **silence-tidies** it (`_tidy_silence`: trim leading/trailing silence and cap
   internal pauses to ~300 ms — CSM sprinkles long mid-utterance pauses that
   otherwise sound halting), and joins chunks with a uniform `reader.gap_sec`
   gap. `progress(done, total)` fires per chunk; `should_stop()` aborts early.
4. **Serve** — the concatenated float32 buffer is written to
   `reader.output_dir` (`~/.readback/reader/<uuid>.wav`) and served at
   `/audio/<id>.wav` for playback and download.

## 4. TTS engine (`readback/tts/`)

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
  `sample_rate`, `current_voice`, `swap_voice`, `supported_voices`, `load`) so the
  server stays engine-agnostic — a future engine is a factory change, not a
  rewrite. `tts.engine` is a single-value enum (`"csm"`).

## 5. LLM (`readback/llm/client.py`)

Only **Summary mode** uses the LLM, via `LLMClient.oneshot()` — a single
non-streaming Ollama `chat` (`think=False`, low temperature) with `<think>`
stripping for GGUF builds that emit inline tags. Full mode skips the LLM
entirely.

## 6. Web layer (`readback/web/`)

- **Server** (`server.py`) — FastAPI; serves the Vite `dist/` build (under
  `web/static/dist/`), the generated audio, and `/ws`.
- **WS protocol** —
  - client → `read {url, mode, voice?}`, `cancel`
  - server → `phase {value}`, `progress {done, total}`,
    `done {title, audio_url, duration_sec, word_count, mode, text?}`, `error {message}`
  - `done.text` carries the spoken summary (Summary mode only) for the
    transcript panel.
- **Frontend** (`web/frontend/`) — React 18 + zustand. The three.js orb and WS
  client live **outside** the React tree as singletons pushing into the store, so
  re-renders never tear down the socket. Components: the URL input + circular
  arrow CTA, the Full/Summary segment + voice `<select>`, the hero-orb busy state
  (phase message + progress + Cancel), the custom `AudioPlayer`, and the summary
  transcript toggle. Single dark "Ghost" theme.
- **Terminal client** (`cli/`, repo root) — Bun + TypeScript + Ink; a second
  consumer of the exact same WS protocol (no server changes). It health-checks
  `/api/config`, auto-spawns `readback` when no server is running (and kills it
  on exit only if it spawned it), mirrors the Ghost palette, and plays the
  finished WAV through `afplay`. Same singleton-outside-the-React-tree pattern
  for its WS client and player.

## 7. CLI & TLS (`readback/__main__.py`)

`readback` parses args (`--host/--port/--model/--config`, TLS via
`--auto-cert` or `--cert/--key`), loads config, and boots uvicorn. `--auto-cert`
generates a self-signed cert (SAN = LAN IP + 127.0.0.1 + localhost, 825-day
validity) under `~/.readback/certs/`, regenerated when the LAN IP changes, and
prints the SHA-256 fingerprint + `/cert.pem` URL so phones/tablets can trust it.

## 8. Extension points

- **New TTS engine** — implement the `Synthesizer` surface and branch on
  `tts.engine`.
- **New voice** — a clone clip (`tts.csm.voices`) or a LoRA adapter
  (`tts.csm.lora_path` + `finetune/`); no code change.
- **Different extractor / summary prompt** — swap inside `reader/extract.py` /
  `reader/summarize.py`; the rest of the pipeline is unaffected.
