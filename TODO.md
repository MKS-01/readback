# TODO — offline article reader (handoff)

Status: **v0.8.0 pivot is functional end-to-end** (URL → extract → optional LLM
summary → CSM TTS offline → in-browser player + download). Branch: `tuning-v1`.

What works now: article extraction (trafilatura + browser-UA fallback), full &
summary modes, offline synthesis with silence-tidying (caps pauses to 0.30s),
read-speech voice references (natural reading tone), WS progress, audio serving,
graceful client-disconnect handling. Verified via the server end-to-end.

---

## 1. Cleanup
- [ ] **Remove dead `tools/` module** (`clock`, `web_search`) — unused by the
      reader. Also strip the tool-calling plumbing from `llm/client.py`
      (`_stream_tokens_with_tools`, `ToolRegistry` TYPE_CHECKING import, the
      `tools` ctor arg). Keep only `oneshot()` + `stream_*` if still wanted.
- [ ] **Legacy static fallback** in `web/static/` (`index.html`, `app.js`,
      `styles.css`, `recorder.worklet.js`) is the old vanilla-JS voice UI — delete;
      the React `dist/` is the only client now.
- [ ] **`config.py` `load()`**: drop the dead Qwen→CSM migration block.
- [ ] **Inert CSM config fields** (`model`, `watermark`, `context_turns`) — decide
      keep vs remove (csm-mlx checkpoint is fixed in the engine).
- [ ] **`voice/` folder** (clone clips) + any clone references in docs — gone with
      cloning; remove.
- [ ] **Generated-WAV rotation**: `~/.readback/reader/` grows unbounded — add a
      cleanup (keep N most-recent / age-out), mirror old `memory.keep_days`.
- [ ] Remove the stray top-level `vox_tinker/` copy (now gitignored).

## 2. Docs (do last — was deferred)
- [ ] **README.md** — full rewrite for the reader: what it is, install
      (`pip install -e .`, csm-mlx note, Python <3.13), run, the two modes,
      voices, where audio is saved. Drop all voice-assistant content.
- [ ] **CLAUDE.md** — rewrite project context for the reader architecture
      (reader/ extract+speak+summarize, csm_engine, server WS protocol). Currently
      still describes the voice-assistant cascade.
- [ ] **ARCHITECTURE.md** — rewrite or fold into README; the cascade/threading
      content is obsolete.
- [ ] **Changelog**: add the v0.8.0 reader-pivot entry.
- [ ] Consider renaming the package `readback` → `vox_tinker` (repo is
      `vox-tinker`); currently still `readback` everywhere.

## 3. Voice improvement
- [ ] **A/B the read-speech references** (`read_speech_a/b/c/d`) per voice; pick the
      best-sounding for "Reading voice A/B". Maybe expose more than two.
- [ ] **Loudness normalize** the final audio (peak hit ~0.88; normalize to a
      consistent target, e.g. -1 dBFS, or RMS-normalize).
- [ ] **Temperature / chunk-size tuning** for long-form fluency (current temp 0.7,
      _MAX_CHARS 280). Try sentence-level vs paragraph chunking.
- [ ] **Degenerate-chunk guard**: a chunk that synths to all-silence is dropped
      (content loss). Detect + retry once (maybe lower temp / re-chunk).
- [ ] **Try `fp32`** for max quality (offline — speed irrelevant) and compare.
- [ ] Evaluate a long-form-tuned TTS if CSM prosody still falls short (MisoTTS-8B
      MLX port was the earlier roadmap idea).
- [ ] Optional: light crossfade at chunk joins to remove any residual seams.

## 4. UI improvement
- [ ] **Polish layout** — current page is functional but basic. Better visual
      hierarchy, spacing, mobile responsiveness.
- [ ] **Show the extracted article** (title + maybe first lines / word count +
      est. listen time) before/while synthesizing, so the user sees what they got.
- [ ] **Progress**: show % + estimated time remaining (we have done/total).
- [ ] **Cancel button** during synth (server already supports `should_stop` via
      disconnect; add an explicit cancel message).
- [ ] **Wire the orb to playback** via an AnalyserNode on the `<audio>` element so
      it reacts to the actual audio (currently phase-driven only).
- [ ] **Download filename** = sanitized article title (not the uuid).
- [ ] **History** of recent reads (title + audio link), backed by the saved WAVs.
- [ ] Nicer error states (paywalled / JS-only / fetch-blocked pages).

## 5. Nice-to-have / functional
- [ ] **Cache by (url, mode, voice)** so re-reading is instant.
- [ ] **Chunked summarization** for very long articles (summary mode currently
      truncates to `summary_max_chars`).
- [ ] Paste raw text (not just URL) as an input source.
