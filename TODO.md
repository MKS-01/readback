# TODO — readback (offline article reader)

Status: **v0.8.0 functional end-to-end** (URL → extract → optional LLM summary →
CSM TTS offline → in-browser player + download). Renamed `local-tts` → `readback`.
Branch: `tuning-v1`.

Done recently: project rename; reader UI (custom player, Full/Summary toggle,
summary transcript + copy, centered layout, circular CTA, hero-orb synthesis state
with **Cancel**); clone-condition voices (`tts.csm.voices`) + LoRA fine-tune
scaffold (`finetune/`); docs rewritten (README, CLAUDE, ARCHITECTURE, SETUP,
changelog); `pyproject` install fixed (`allow-direct-references`); removed the
`vox_tinker/` stub.

---

## 1. Cleanup
- [ ] **Remove dead `tools/` module** (`clock`, `web_search`) — unused by the
      reader. Also strip the tool-calling plumbing from `llm/client.py`
      (`_stream_tokens_with_tools`, `stream_response`, `ToolRegistry` import, the
      `tools` ctor arg). Keep only `oneshot()`.
- [ ] **Legacy static fallback** in `web/static/` (`index.html`, `app.js`,
      `styles.css`, `recorder.worklet.js`) — old vanilla-JS voice UI; the React
      `dist/` is the only client now.
- [ ] **`config.py load()`**: drop the dead Qwen→CSM migration block.
- [ ] **Vestigial config fields**: inert `CsmTTSConfig` (`speed`, `model`,
      `watermark`, `context_turns`) and `OllamaConfig.system_prompt` — remove or
      keep-with-comment.
- [ ] **Generated-WAV rotation**: `~/.readback/reader/` grows unbounded — keep N
      most-recent / age-out.

## 2. Voice quality
- [ ] **Loudness normalize** the final audio (peak ~0.88 → consistent target,
      e.g. −1 dBFS or RMS-normalize).
- [ ] **Degenerate-chunk guard**: a chunk that synths to all-silence is currently
      dropped (content loss). Detect + retry once (lower temp / re-chunk).
- [ ] **Try `fp32`** for max quality (offline — speed irrelevant) and compare.
- [ ] **Temperature / chunk-size tuning** for long-form fluency (temp 0.6,
      `_MAX_CHARS` 280). Sentence- vs paragraph-level chunking.
- [ ] Optional: light crossfade at chunk joins to remove residual seams.
- [ ] A/B the built-in read-speech references; consider exposing more than two.

## 3. UI
- [ ] **Show the extracted article preview** (title + word count + est. listen
      time) before/while synthesizing, so the user sees what they got.
- [ ] **Progress**: show % + estimated time remaining (we have done/total).
- [ ] **Wire the orb to playback** via an AnalyserNode on the `<audio>` element so
      it reacts to the actual audio (currently phase-driven only).
- [ ] **Download filename** = sanitized article title (not the uuid).
- [ ] **History** of recent reads (title + audio link), backed by the saved WAVs.
- [ ] Nicer error states (paywalled / JS-only / fetch-blocked pages).

## 4. Nice-to-have
- [ ] **Cache by (url, mode, voice)** so re-reading is instant.
- [ ] **Chunked summarization** for very long articles (Summary mode currently
      truncates to `summary_max_chars`).
- [ ] **Paste raw text** (not just a URL) as an input source.
