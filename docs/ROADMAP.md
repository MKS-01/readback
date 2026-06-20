# Roadmap

Where readback is headed. The [README](../README.md) documents what's supported
**today**; this file tracks what's planned and what's recently shipped. It is the
single open-item tracker for the project (no `TODO.md`).

Direction now: **audio quality and CLI performance first**. New features are
intentionally lower priority.

---

## Recently shipped

- **Summary/audio speedup — disabled LLM chain-of-thought** 🏁 _key milestone_.
  Qwen3.5 defaulted to thinking and spent its whole token budget on an untagged
  "Thinking Process:" monologue — slow, truncated before the real answer, and
  (untagged, so the stripper missed it) read aloud. `enable_thinking=False` on the
  chat template cut a 215-word article from **~76 s / 2760 words → ~4 s / ~190
  words**; since synthesis time scales with summary length, audio dropped
  proportionally. Plus a `max_tokens` 4096→1024 safety bound and a hard ~250-word
  prompt ceiling.
- **Eager model warm-up** — the server lifespan kicks off `ensure_loaded()` at
  boot so CSM + LLM weights are warm before the first read, hiding the cold-start
  "loading models" stall.
- **Loudness normalization** — every read is peak-normalized to 0.95 so clone
  voices no longer come out ~18 dB quieter than the built-ins (`_peak_normalize`
  in `speak.py`).
- **Instant CLI quit** — `stopServer` SIGKILLs the spawned server outright; the
  old SIGTERM-then-busy-wait stalled every quit ~1.5 s.
- **Pi + PiZoW integration** — readback is live on a home Pi under
  [PiZoW](https://github.com/MKS-01/pizow), accessible from any device on the
  local network; the dashboard is fully mobile-responsive (v3.2.0).
- **Pi deployment** — `scripts/deploy-pi.sh` + `sync-pi.sh` push the dashboard +
  library to a home Pi (no TTS/LLM on Pi) (v3.2.0).
- **UI/UX polish pass** — animations + a redesigned landing page and
  rounded-corner dashboard (v3.1.0).
- **Library dashboard + persistence** — searchable SQLite library, replay any
  past read in the browser (v3.0.0).
- **CLI `/model` switch** with RAM-fit verdicts (v1.1.0).
- **Audio-quality tuning pass** — `temperature 0.6`, `fp32`, 280-char
  sentence-aware chunks.

---

## 🎧 Audio quality — priority

- [x] Loudness-normalize the final WAV to a consistent target — peak-normalized to 0.95 (`_peak_normalize`), so clone voices match the built-ins
- [ ] Light crossfade at chunk joins to remove residual seams (chunks join with a flat 0.18 s gap)
- [ ] Degenerate-chunk guard — an all-silence chunk is silently dropped (`_tidy_silence` → empty); detect + retry once
- [ ] LoRA fine-tune for higher fidelity (pipeline in [`../src/finetune/`](../src/finetune/README.md))
- [ ] More reading voices — A/B and expose the built-in read-speech references beyond the two defaults + `codeword`; eventually clone a new voice from the CLI instead of editing `config.yaml`

## ⚡ CLI — tuning & performance — priority

- [x] **Summary mode no longer runs away** — `enable_thinking=False` + `max_tokens` cap + prompt length ceiling; the LLM is no longer the bottleneck (~4 s summaries, audio shrinks with the shorter text)
- [x] Trim startup / model warm-up — server eagerly loads CSM + LLM at boot so the first read isn't cold (`ensure_loaded()` in the lifespan hook)
- [ ] Faster synthesis — tune the controllable knobs (precision, chunking, warm-up); ultimately bounded by your Mac's GPU / unified memory
- [ ] Cache by (url, mode, voice) so re-reading is instant
- [ ] Surface clearer progress (% + ETA, not just per-chunk)
- [ ] Parallelize multi-page OCR + the map-phase summary calls — both are sequential today; the win scales with page count (mlx-lm's `generate()` supports batched prompts natively)

## 🍓 Pi — shipped

- [x] Host the dashboard on the local Pi network (`scripts/deploy-pi.sh`)
- [x] Lite, read-only server on the Pi — library REST + `/audio` + static dashboard, no LLM/TTS
- [x] Sync script — push new reads (DB rows + WAVs) Mac → Pi (`scripts/sync-pi.sh`)
- [x] Live on home network via [PiZoW](https://github.com/MKS-01/pizow) — PM2-managed, survives reboots, accessible from any device
- [ ] Generated-WAV rotation so the synced store doesn't grow unbounded (dashboard delete handles it manually today)

## 📄 More input sources

- [x] **Image OCR** — drop an image path; mlx-vlm vision model extracts the text and reads it aloud (`_ocr_via_mlx`)
- [x] **Multi-page / book scans** — a folder or glob of page images is OCR'd in filename order and stitched into one continuous document (`fetch_multi_page`)
- [x] **Source-aware tones** — a URL reads as a livelier article; an image/folder reads as a measured book that opens by naming its chapter/topic (`pipeline/tones.py`, auto by source)
- [ ] `/tone` override + persisted pref, and a 3rd tone (technical paper / news) — auto-only with two tones today
- [ ] Read **local documents**, not just URLs — `.txt` and `.pdf` → voice
- [ ] Paste raw text directly as a source

## 🔭 Later

- [x] Automation + testing — `pytest` suite (pure logic: chunking, silence-tidy, text scrub, library, think-stripper) + GitHub Actions CI on Python 3.10–3.12
- [ ] Broaden coverage — server/WS integration tests, an end-to-end synth smoke test on a macOS runner
- [x] Chunked summarization for very long articles — map-reduce in `summarize.py` (batches → condense → combine), so book scans summarize end-to-end instead of truncating at `summary_max_chars`
- [ ] Trial larger/newer summary models for quality (Qwen3-30B-A3B, Qwen2.5-32B, Gemma-2-27B…) — shortlist + eval method in [PLAN.md](PLAN.md) (2026-06-20)
- [ ] UX niceties (lower priority): extracted-article preview before synth, download filename = article title, nicer error states for paywalled / JS-only pages
