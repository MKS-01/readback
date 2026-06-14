# Roadmap

Where readback is headed. The [README](../README.md) documents what's supported
**today**; this file tracks what's planned and what's recently shipped. It is the
single open-item tracker for the project (no `TODO.md`).

Direction now: **audio quality and CLI performance first**. New features are
intentionally lower priority.

---

## Recently shipped

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

- [ ] Loudness-normalize the final WAV to a consistent target (e.g. −1 dBFS) — levels vary with voice and chunk
- [ ] Light crossfade at chunk joins to remove residual seams (chunks join with a flat 0.18 s gap)
- [ ] Degenerate-chunk guard — an all-silence chunk is silently dropped (`_tidy_silence` → empty); detect + retry once
- [ ] LoRA fine-tune for higher fidelity (pipeline in [`../src/finetune/`](../src/finetune/README.md))
- [ ] More reading voices — A/B and expose the built-in read-speech references beyond the two defaults + `kay`; eventually clone a new voice from the CLI instead of editing `config.yaml`

## ⚡ CLI — tuning & performance — priority

- [ ] Faster synthesis — tune the controllable knobs (precision, chunking, warm-up); ultimately bounded by your Mac's GPU / unified memory
- [ ] Cache by (url, mode, voice) so re-reading is instant
- [ ] Trim startup / model warm-up and surface clearer progress (% + ETA, not just per-chunk)

## 🍓 Pi — shipped

- [x] Host the dashboard on the local Pi network (`scripts/deploy-pi.sh`)
- [x] Lite, read-only server on the Pi — library REST + `/audio` + static dashboard, no LLM/TTS
- [x] Sync script — push new reads (DB rows + WAVs) Mac → Pi (`scripts/sync-pi.sh`)
- [x] Live on home network via [PiZoW](https://github.com/MKS-01/pizow) — PM2-managed, survives reboots, accessible from any device
- [ ] Generated-WAV rotation so the synced store doesn't grow unbounded (dashboard delete handles it manually today)

## 📄 More input sources

- [ ] Read **local documents**, not just URLs — `.txt` and `.pdf` → voice
- [ ] Paste raw text directly as a source

## 🔭 Later

- [ ] Automation + testing — CI, unit / integration coverage
- [ ] Chunked summarization for very long articles (Summary mode truncates to `summary_max_chars`)
- [ ] UX niceties (lower priority): extracted-article preview before synth, download filename = article title, nicer error states for paywalled / JS-only pages
