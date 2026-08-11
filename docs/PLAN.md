# Plans

Planning history for readback — newest entry on top, older entries kept below for
tracking. Each entry carries a date and a status (`proposed` / `in progress` /
`done` / `superseded`).

---

## 2026-08-12 — Batched CSM synthesis (~2x); chunk band change tried and reverted

**Status: PARKED — not shipped, retry in a later session.** Branch
`perf/batched-synthesis` (2 commits, unpushed, based on `optimisation-2`). The
speedup works and is verified, but **audio quality was judged not up to the
mark** on real reads and the user parked it. Do NOT merge without redoing the
listening check.

⚠ **Open symptom: the voice sounds MUFFLED.** Not yet explained, and measurement
says it is *not* the batching: mean spectral centroid and energy above 4 kHz came
out batched 1160 Hz / 7.05%, sequential 1108 Hz / 5.46%, reference-quality read
1158 Hz / 6.49% — i.e. batched is marginally *brighter* than sequential and
matches the good reference. So muffling most likely predates this branch and
lives in the VOICE path, not the batch path. Next leads, in order:
  1. the `codeword` clone reference itself (`src/voice/voice_codeword.wav` — a
     12 s CSM-bootstrapped clip, i.e. a copy of a copy) — try a clean human clip
     or a built-in reading voice (`conversational_a`) as a control;
  2. `tts.csm.precision` — bf16 vs fp32 (fp32 is the fidelity setting; ~2x slower);
  3. `ref_max_sec` / reference length effects on timbre;
  4. `_peak_normalize` (0.95 peak) interacting with quiet clone references.
  A/B the SAME text on `conversational_a` vs `codeword` first — if only the clone
  is muffled, it's the reference clip, and none of this is a synthesis bug.

**What is already done and verified on the branch** (keep, don't redo): batched
generation with per-row temperature and per-row frame bounds, evened batch
splits, length bucketing, sequential fallback, 55 passing tests, and the two
reverts/fixes below. Profiling a full read showed
synthesis was **77%** of wall time (fetch 3.8 s · summarize 15.2 s ·
synthesize 65.1 s, for 93 s of audio) at a flat RTF ~0.67 regardless of chunk
size.

**Why it was slow.** Not compute — *launch latency*. CSM emits one frame per
80 ms of audio and each frame is 1 backbone step + 31 **sequential** decoder
steps on a 1B model: ~400 tiny matmuls per audio-second, with the GPU idle in
between. Measured per-frame cost barely moves with batch size (ms/frame → audio
per wall-second): 1 → 51.6/1.55 · 2 → 80.5/1.99 · 4 → 82.1/3.90 · 8 →
84.8/**7.55**. Eight times the work for 1.64x the time.

**What shipped.** `CsmEngine.synthesize_batch` mirrors
`csm_mlx.generation.generate` over the batch dimension `generate_frame` already
supports — prompts are `ref ++ text` tokens left-padded to the batch max
(`token_mask` zeroes the pads), one `make_prompt_cache`, per-row EOS tracking,
`decode_audio` per row. `_make_batch_sampler` gives each row its **own**
sampling temperature (shape `(B, 1)`, mirroring mlx_lm's `apply_top_k` →
`categorical_sampling` chain), so batching does not flatten
`_expressive_temperature`. `speak.py` drives it via `_length_buckets` (sort by
length: pads stay small and rows finish together) + `_batches`, with the
degenerate-chunk retry batched and a **fallback to the old sequential loop** if
the batch path raises. New `tts.csm.batch_size` (default 8).

**The chunk band change was tried and REVERTED.** Batching makes small chunks
cheap, so the band was narrowed [280, 400] → [120, 200] to give
`_expressive_temperature` a per-sentence window instead of a per-paragraph one.
On device it sounded worse — delivery shifted tone every sentence or two instead
of settling ("audio is not stable, tone keeps changing") — so the band is back at
[280, 400], the config behind the reference-quality reads. ⚠ Chunk size is a
DELIVERY setting, not a speed setting; speed comes from `batch_size`, which
doesn't change how the text is divided.

Instead, `max_audio_length_ms` was raised **20 s → 30 s**. At [280, 400] a
370-char chunk measured 19.84 s of audio against the 20 s bound — right at the
edge of being clipped mid-sentence (the same text yields 21.84 s given room).
The bound is a runaway-generation guard, and generation stops at EOS, so a higher
ceiling costs nothing (measured identical wall time at 20 s vs 60 s caps).

⚠ **Per-row generation bounds are load-bearing.** The first version took a
single batch-wide frame budget (the max over rows), so a SHORT row that never
emitted EOS kept generating on the LONGEST row's budget and tailed off into
babble — reported as "the ending is broken", and visible as a batch rendering
13 s longer than the same text done sequentially. `frame_bounds()` now returns
one bound per row, guarded by `test_frame_bounds_are_per_row_not_batch_wide`.

Two more findings worth keeping:
- ⚠ **A runty tail batch wastes the win.** A batch's cost is nearly flat in
  batch size, so 11 chunks split 8+3 measured RTF 0.33 where an evened 6+5 gave
  **0.26**. `_batches` now evens the groups out.
- ⚠ **Don't raise `batch_size` much past 8** — the loop runs until *every* row
  hits EOS, so one runaway row stalls the batch: 16 measured RTF 0.17 and 0.37
  on consecutive runs, where 8 measured 0.23 twice.

**Verified.** 55 pytest pass (11 new, all pure-logic with a fake synth: document
order, per-chunk progress, cancel between batches, degenerate retry, per-row
temperature, per-row frame bounds, even batch splits, and both fallback paths).
On device at the shipped [280, 400] band, same summary: **61.3 s → 28.6 s**
synthesis (RTF 0.65 → 0.25). Padding worst case — a 3-char row batched with a
112-char row — produced proportionate audio for both. Live `/ws` reads:
Wikipedia Fresnel lens **total 44.5 s vs the 84.1 s baseline**, plus posts from
claude.com/blog and android-developers.googleblog.com. Cancel stops after one
batch (8/36 chunks, 8.0 s) and keeps the partial audio. **Batched vs sequential
output was judged by ear** and accepted; the band change was rejected the same
way.

⚠ **Automated audio-quality metrics failed here.** A drift script (per-chunk
pitch sd, loudness sd, spectral centroid) scored a reference-quality read at
23.0 Hz pitch sd and a read the user rejected at 22.4 Hz — i.e. it ranked the bad
one better. It measures natural sentence-to-sentence variation, not delivery
instability. Judge delivery changes BY EAR; use the numbers only to catch gross
breakage (silence fraction, duration, ZCR).

⚠ **Benchmark gotchas discovered here**, both of which produced wrong numbers
before being caught: (1) `chunk_text` splits on every `\n`, so a hard-wrapped
test fixture yields one chunk per *line* and silently defeats band changes —
measure with real article prose; (2) `csm_mlx.generation` binds its
`default_stream` to the thread that imports it, so a second `Synthesizer` in one
process dies with "no Stream(gpu, 0)" — A/B benchmarks must fork per config.

**Not done:** streaming playback (time-to-first-audio 84 s → ~8 s), LLM
speculative decoding for the 15–25 s summary step.

---

## 2026-08-12 — One model for summary + OCR (the `ocr:` block removed)

**Status: done** — branch `optimisation-2`. A dependency audit found the OCR
model redundant: `mlx-community/Qwen3.5-9B-4bit`, already loaded for summaries,
is `Qwen3_5ForConditionalGeneration` with a `vision_config` — a VLM — and the
installed mlx-vlm 0.6.3 ships a `qwen3_5` handler. So `ocr.model`
(`Qwen2.5-VL-7B-Instruct-4bit`, 5.65 GB) was a second download doing a job the
summary model already covers. **Supersedes** the 2026-06-20 entries that split
OCR into its own `ocr:` section and added `/vision`.

**What shipped.** OCR runs on `cfg.llm.model`. Deleted: `OcrConfig` + the `ocr:`
YAML block, the `vision_model` field on the WS `read` message / `/api/config` /
WS `config`, `current_vision` + the per-model `vision` tag on `/api/models`, the
CLI `/vision` command, `ModelList`'s `kind` prop, the `visionModel` pref, and
`fetch_article`/`fetch_multi_page`'s `vision_model` parameter. `list_models`
now *filters out* vision-only checkpoints (`_is_vision_model`) rather than
tagging them — the listed model must also drive Summary mode through mlx-lm.
Old configs still load unchanged: `llm.vision_model` hits pydantic's
`extra="ignore"`, an `ocr:` block hits the unknown-top-level-key drop.
`llm.model` stays `Qwen3.5-9B-4bit` — the audit floated a 4B for both, but URL
summary quality is the priority and OCR was the riskier half of that downgrade.

Two bugs found while verifying, both fixed here:
- ⚠ **Transparent PNGs OCR'd to garbage.** mlx-vlm flattens alpha onto BLACK, so
  a page of black-on-transparent text arrives as a solid black rectangle; the
  model doesn't error, it confidently returns `$$\frac{1}{2}$$`. `_has_alpha`
  (sips) now routes any alpha image through the JPEG conversion, which flattens
  onto white. This was pre-existing, not introduced by the model swap.
- `reading page N / M` showed "page 3 / 2" on a 2-page book — `fetch_multi_page`
  fires a final `progress(total, total)` as a completion signal; the server's
  phase string now clamps with `min(pi + 1, tot)`.

Also removed a redundant temp-file round-trip: `_image_to_jpeg` wrote a temp
JPEG, read it back to bytes, deleted it, and the caller wrote those bytes to a
*second* temp file. It now returns the path directly.

**Verified.** 44 pytest pass; `Config.load()` on a config carrying both stale
keys loads clean with no `ocr` attribute; `/api/config` + `/api/models` carry no
vision fields and the old Qwen2.5-VL correctly drops out of the picker; CLI
`tsc --noEmit` + `bun build` clean. End-to-end over a live `/ws`: a Wikipedia
URL → Summary mode read (5209 words, 93 s audio, summarize 15.2 s / synthesize
65.1 s), and a 2-page transparent-PNG book folder → both pages OCR'd verbatim,
sentence stitched across the page seam, title `Chapter Four` from the opening
lines. Single-image OCR reproduces the source text exactly.

**Not done:** the 4B model swap (11.6 GB → 3.06 GB) and any translation path
from the same audit; the unreferenced 19 GB `Qwen3.6-35B-A3B-4bit-DWQ` in the HF
cache is still there. The older "auto-pick OCR model by source" follow-up is
moot — there's one model now.

---

## 2026-07-02 — CLI playback speed controller (/speed + player +/- keys)

**Status: done** — branch `fix/summary-padding-short-articles`. User found the
reading pace a bit slow. Measured the two most recent reads: the *speech* is
170–187 wpm (normal-to-brisk) — the slowness is pauses (10–11% of runtime) and,
fundamentally, taste. CSM has no speed control, so pace is a playback concern:
added a speed controller to the CLI player on `afplay -r RATE -q 1`
(high-quality pitch-preserving rate scaling). `+`/`-` in the player steps
0.1× (0.5–2×, live — restarts afplay at the current position via the seek-slice
mechanism); `/speed <x>` sets it from the input screen; the rate shows next to
the progress bar when ≠1× and persists to `~/.readback/cli.json` (`speed`).
⚠ `player.ts`'s `elapsed` now advances at `rate ×` wall time (audio position,
not wall clock) so seek slices and the synced transcript stay aligned.

**Verified** via tmux-driven CLI (drive-cli): `/speed` show + set + persist;
`+`/`-` mid-play (afplay respawns with `-r 1.3`/`-r 1.1`, indicator updates);
pause/resume/seek/transcript all correct at non-1× rates; clean quit, no
orphaned afplay. `tsc --noEmit` clean; binary rebuilt.

---

## 2026-07-02 — PR #21 review fixes: ceiling trim, word-count threading, fast chunk band, fragment drop

**Status: done** — branch `fix/summary-padding-short-articles`. A multi-angle
review of PR #21 (time named the most important factor) surfaced four issues;
all fixed on the branch:

1. **Chunk band [120, 200] → [280, 400]** (`speak.py`). Measured on a
   ~2,100-word text: the low band produced ~100 chunks vs 40 at the old fixed
   400 (2.5-3x the CSM prefills — +60-120s on a Full-mode read at 1-2s/prefill);
   the PR's own 104.9s→82.7s synth "win" came from the summary shrinking, not
   the chunking. Verified randomization itself is free (fixed 200 vs randomized
   [120, 200] chunk identically — boundaries dominate), so the cadence variation
   and per-chunk expression are kept; only the band moved. Post-fix: 52-58
   chunks on the same text.
2. **250-word ceiling enforced in code** (`_trim_to_word_ceiling`,
   `summarize.py`). The prompt's HARD LIMIT alone still measured 313 words from
   a 3,446-word source; the trim clips at a sentence boundary at
   `SUMMARY_WORD_CEILING` (exported from `tones.py`, single source of truth),
   always keeping ≥1 sentence. Closes the ROADMAP overshoot item — and every
   trimmed word is synthesis time saved.
3. **Map-reduce length anchor fixed** (`source_words` threading,
   `summarize.py`). The reduce step passed the joined digests as `body`, so the
   new word-count anchor measured the compressed digests instead of the source —
   mis-calibrated on exactly the long inputs map-reduce exists for. The original
   `article.word_count` now rides through `_map_reduce` (and its recursion) into
   every `_summarize_once`.
4. **Fragment drop fixed** (`chunk_text`, `speak.py`). CONFIRMED by the review:
   a sub-`_MIN_CHARS` buf ("Wow!") followed by a sentence overflowing a low
   random cap was silently discarded — lost in ~21% of runs (415/2000) on the
   [120, 200] band. Now carried into the next piece (or emitted as its own tiny
   chunk if that would exceed `_MAX_CHARS`). Also added `_hard_split`: a
   comma-free run > `_MAX_CHARS` (which risked the 20s `max_audio_length_ms`
   mid-sentence cutoff) now space-splits under the cap.

Cleanups from the same review: the duplicated length-policy prose in the two
tone prompts hoisted into `_LENGTH_RULES`/`_PLAIN_PROSE_RULE` (`.format`-ed per
tone, one source of truth); `_summarize_once` uses the threaded source count
instead of re-deriving `Article.word_count`; stale "~400 chars" line in
ARCHITECTURE.md refreshed.

**Verified.** 44/44 pytest (6 new: 2 chunking regressions + 4 ceiling-trim).
Empirical: "Wow!" retained in 2000/2000 runs (was ~79%); ~2,100-word text
chunks 52-58 (was ~100); tone prompts render with no leftover `{src}`/`{out}`
placeholders. Docs synced: CLAUDE.md, config.yaml guide, ARCHITECTURE.md,
ROADMAP.md, TESTS.md.

---

## 2026-07-02 — Merge `optimize/summary-map-reduce-threshold`, verify on a real slow read

**Status: done** — branch `fix/summary-padding-short-articles`. User reported a
real CLI read ("Chasing a Phantom Jump", 3,446 words / 20,701 chars) took 140.4s
and asked whether that was worth it. Investigation found `fix/summary-padding-
short-articles` had branched off `main` *before* the `summary_max_chars`
16000→60000 fix (see that entry below) landed, so it was still on the old
16,000-char threshold — this 20,701-char article just barely exceeded it and
needlessly map-reduced. Worse, the map-reduce path's final reduce step anchors
its word-count target off the *combined digest* length (not the original
article), so it also blew through the 250-word hard ceiling (403 words).

**Fix.** Merged `optimize/summary-map-reduce-threshold` into this branch
(one conflict, in this file, both branches adding entries at the top — resolved
by keeping both, correctly ordered).

**Verified** — full pipeline, same URL, before vs after the merge:

| | before (16K threshold, map-reduce) | after (60K threshold, single-pass) |
|---|---|---|
| summarize | 34.6s | 13.4s |
| summary length | 403 words (over the 250 ceiling) | 313 words (better, still slightly over) |
| synthesize | ~104.9s (est. from the original 140.4s total) | 82.7s |
| **total** | **140.4s** | **97.0s** (31% faster) |

Noted, not chased further: 313 words is closer to the 250-word ceiling than
403 but still exceeds it — the word-count-anchor fix from the padding entry
helps but isn't fully reliable on longer single-pass inputs; a candidate for a
future follow-up. Full `pytest` suite: 38/38 pass after the merge.

---

## 2026-07-02 — Revert precision to bf16 (keep the 200-char / dynamic chunking)

**Status: done** — branch `fix/summary-padding-short-articles`. Follow-up to the
Max-quality preset entry below: user asked to stick with `bf16` after all.
Reverted `config.yaml`'s `tts.csm.precision` back to `bf16` — per the engine's
own docs, bf16 has no audible quality loss at normal listening (its only
downside is a nonexistent one here, since the docs already say fp32 is for
fixing audible artifacts on a clone voice, not a baseline upgrade). The
`_MAX_CHARS: 200` + randomized chunk-boundary changes from the two entries below
are unaffected — those are what actually drove the voice-quality/expression
improvements the user asked for; the precision knob was the one piece of that
change to walk back. Updated the speed/quality guide comments in `config.yaml`
and `CLAUDE.md` to describe the current combination (bf16 + 200/randomized) as
its own row rather than reusing the "Max quality" fp32 label. Full `pytest`
suite: 38/38 pass.

---

## 2026-07-02 — Randomize chunk boundaries instead of a fixed cap

**Status: done** — branch `fix/summary-padding-short-articles`. Follow-up to the
Max-quality preset switch above: user asked to make chunk sizing dynamic and
keep varying it, rather than every chunk hitting the same fixed 200-char cap.
A uniform cap means every chunk is close to the same length, which reads with a
mechanical, same-every-time breath cadence — real speech doesn't chunk that
evenly.

**Fix.** `chunk_text` (`speak.py`) now draws each chunk's actual cap fresh via
`_next_chunk_cap()`, a `random.randint` between a new `_MIN_CHUNK_CHARS` (120)
and the existing `_MAX_CHARS` (200) — redrawn every time a new chunk starts, so
consecutive chunks vary in length instead of all targeting the same number. The
over-long-sentence comma-split safety net still checks against the fixed
`_MAX_CHARS`, not the random per-chunk cap, since that's a hard ceiling, not a
pacing choice. This also compounds with the per-chunk `_expressive_temperature`
feature: a shorter random cap is more likely to isolate a single sentence into
its own chunk (and its own temperature) instead of merging it with a
differently-toned neighbor.

**Verified.** Ran `chunk_text` 3x on the same fixed input text: got 3 chunks
(lengths 152/82/164) on runs 1 and 3, 4 chunks (75/76/82/164) on run 2 —
confirmed genuinely different boundaries across runs, not just different
content. Existing chunking tests (`test_chunk_text.py`) don't assert exact
chunk boundaries, only bounds (`len(c) <= _MAX_CHARS`) and paragraph-splitting
behavior, both of which hold regardless of which cap was drawn; ran them 20x in
a loop to rule out flakiness from the new randomness — stable every time. Full
`pytest` suite: 38/38 pass.

---

## 2026-07-02 — Switch to the Max-quality synthesis preset (fp32 + 200-char chunks)

**Status: done** — branch `fix/summary-padding-short-articles`. After reviewing
the per-chunk expression change, user asked to pick "the best version" for voice
quality and summary accuracy, explicitly accepting a slighter delay in exchange.
The already-documented "Max quality" preset in `config.yaml`'s speed/quality
guide (`tts.csm.precision: fp32` + `_MAX_CHARS: 200` in `speak.py`) was exactly
this tradeoff, previously left off by default in favor of "Fast" (`bf16` / 400).
Switched both: `config.yaml` → `precision: "fp32"`, `speak.py` → `_MAX_CHARS = 200`.

Smaller chunks are a direct win for the expressiveness feature from the prior
entry too — `_expressive_temperature` nudges the *whole* chunk from whichever
punctuation rule matches, so more, shorter chunks means the nudge tracks the
actual sentence that earned it instead of averaging over a bigger span.

**Verified** — same dramatic test paragraph as the expression-feature entry
(measured intro → exclamation → question → dense factual close), regenerated
under the new preset:

| | 400 chars / bf16 (before) | 200 chars / fp32 (after) |
|---|---|---|
| chunks | 2 | 5 |
| temperatures | 0.88, 0.77 | 0.77, 0.88, 0.84, 0.80, 0.80 |

The calm opening sentence, which previously got dragged into the same chunk (and
temperature) as the exclamation that followed it, now gets its own chunk and its
own measured 0.77 — the finer resolution the "known limitation" note in the
prior entry called out. Synth wall time for this short sample went from ~2 chunks
worth to 26.6s for 39.4s of audio (5 chunks) — the expected "up to ~2×" cost of
the Max-quality preset, accepted per the user's explicit trade-off call. Played
both samples back with `afplay` for a live A/B. Full `pytest` suite: 38/38 pass.

---

## 2026-07-02 — Content-driven expression: per-chunk delivery temperature

**Status: done** — branch `fix/summary-padding-short-articles` (extends the tone
prompt work from the padding fix above). User asked for a more natural, human
delivery where expression shifts with the content instead of one flat register
for the whole read. CSM has no direct emotion/prosody control API — the only
delivery lever it exposes is sampling temperature (`tts.csm.temperature`), which
was previously set **once per read** from the tone (`ARTICLE` 0.8 / `BOOK` 0.6)
and held fixed for every chunk.

**Fix.** `_expressive_temperature(chunk, base)` in `speak.py` nudges the tone's
base temperature per chunk from its punctuation — a real, trained-on prosody
signal: `!` → +0.08 (emphatic), `?` → +0.04 (questioning), 3+ commas with
neither → −0.03 (dense/measured), clamped to `[0.55, 0.95]` (below ~0.55 a short
clone reference destabilizes, per existing voice-cloning notes). `synthesize_article`
takes a new `base_temperature` param and calls `synth.set_temperature(...)`
per chunk instead of once up front; `server.py` passes `tone.temperature` through
instead of setting it before the loop. Also nudged both tone `summary_system`
prompts (`tones.py`) to write with natural spoken rhythm — varied sentence
length, real emphasis on a genuinely notable point — rather than a flat,
even-register list of facts, since Summary mode's generated text is the other
lever available for varying expression (Full mode reads the source verbatim,
so only its own natural punctuation drives this).

**Verified.** Real `Synthesizer` (no stub): a mixed-punctuation paragraph split
into 2 chunks got temperatures 0.88 (a chunk with `!`/`?`, lively section) and
0.77 (a comma-dense explanatory chunk, no `!`/`?`) from a base of 0.8 — confirmed
real variation across chunks. Full `pytest` suite: 38/38 pass (the existing
`_FakeSynth` test stub never receives `base_temperature`, so `set_temperature`
is never called on it — no behavior change for those tests).

**Known limitation.** Granularity is **per chunk (~400 chars), not per
sentence** — `chunk_text`'s merge-up-to-400-chars behavior (tuned for synthesis
speed) can fold a lively and a measured sentence into one chunk, which then gets
whichever punctuation rule matches first. Finer per-sentence expression is
possible by lowering `_MAX_CHARS` (already a documented, config-driven
speed/quality tradeoff in `config.yaml`) at the cost of more, slower chunks —
left as a follow-up rather than silently reintroducing the synthesis slowdown
the July 2026 tuning pass removed.

---

## 2026-07-02 — Stop Summary mode padding short articles with invented filler

**Status: done** — branch `fix/summary-padding-short-articles`. Reviewing a real
library read (Android developer blog, 189-word source) surfaced a content-quality
bug: the spoken summary came out **243 words — longer than the source** — and
contained generic, ungrounded wrap-up sentences ("these changes represent a
significant shift toward industry-wide safety standards", "protect users from
unverified or malicious applications") that weren't in the article at all. The
`ARTICLE`/`BOOK` `summary_system` prompts (`pipeline/tones.py`) said "don't pad"
but only gave the model an upper bound (250 words) with no sense of what "short"
meant for a given source, so it drifted toward the ceiling regardless of input
length.

**Fix.** `_summarize_once` (`summarize.py`) now spells out the source's word
count in the user prompt (`"Article (189 words): ..."`) as a concrete anchor.
Both tone prompts were rewritten to target roughly half the source's word count,
explicitly frame 250 words as a ceiling reserved for genuinely long sources, and
forbid wrap-up/editorializing sentences not grounded in a specific fact from the
source.

**Verified** — same 189-word Android article, direct `summarize_article` calls
against the live LLM:

| | before | after |
|---|---|---|
| summary length | 243 words (padded, longer than source) | 188 words, zero invented claims |

Checked the fix doesn't regress long-form coverage: the 5,240-word "Haiku"
Wikipedia article still produces a 280-word summary (near the ceiling, as
intended for content-rich sources) rather than being clipped short. Full
`pytest` suite: 38/38 pass.

---

## 2026-07-02 — Raise `summary_max_chars` 16000 → 60000 (stop unnecessary map-reduce)

**Status: done** — branch `optimize/summary-map-reduce-threshold`. Summary mode's
single-pass/map-reduce threshold (`reader.summary_max_chars`) was 16,000 chars
(~4K tokens) — ~60x more conservative than the configured summary LLM
(`mlx-community/Qwen3.5-9B-4bit`, 262,144-token context, confirmed via its HF
`config.json`). Most long-form web articles were paying for 3-4 sequential
`oneshot` calls (map digests generated then discarded once merged) when one call
would do. Raised the default to 60,000 chars (~15K tokens, still <2% of the
model's context) in `config.yaml`, `config.pi.example.yaml`,
`ReaderConfig.summary_max_chars`, and `summarize_article`'s default param.
Map-reduce itself is unchanged — it still exists for genuinely huge inputs
(book scans) — and since the same value sizes each map batch, anything that
still map-reduces now does so in fewer, larger batches too.

**Verified — live before/after read** (Wikipedia "Haiku" article, 33,143 chars /
5,240 words, Summary mode, cache cleared between runs so both timings are cold):

| | before (map-reduce, 3 sections) | after (single-pass) |
|---|---|---|
| summarize | 51.3s | 13.4s |
| synthesize | 50.0s | 57.6s |
| **total conversion** | **102.2s** | **72.0s** (~30% faster) |

Summary quality/length unaffected (227-word spoken summary either way — the tone
prompt + `max_tokens` ceiling governs that, untouched by this change). Also
confirmed map-reduce still triggers correctly above the new threshold: a
225,900-char synthetic document packed into 4 batches and produced a coherent
207-word summary in 39.8s. Full `pytest` suite: 38/38 pass.

**Merged into `fix/summary-padding-short-articles` on 2026-07-02**, after this
threshold gap was caught reviewing a real read that unnecessarily map-reduced
(20,701 chars, just over the old 16,000 cutoff) — see the merge note in that
branch's most recent entry above for the concrete before/after.

---

## 2026-06-24 — Faster synthesis + CLI generation timer + venv auto-detect

**Status: done** — branch `optimisation`. Synthesis speed tuning: default
precision fp32 → bf16 (~6% faster), chunk cap 280 → 400 chars (~30% fewer CSM
prefills), sampler cached per (temperature, top_k). Speed/quality preset guide
added to `config.yaml`. CLI player now shows "Xs to generate" for live reads.
Server spawn uses `.venv/bin/python3 -m readback` directly (no activation
needed); stderr captured so crashes show the actual error. Fixed library
migration ordering (ALTER TABLE before index creation).

---

## 2026-06-24 — Degenerate-chunk guard, crossfade joins, read cache

**Status: done** — branch `optimisation`. Three audio-quality and performance
improvements shipped together.

**What shipped.** (1) Degenerate-chunk guard: if `_tidy_silence` returns empty
(all silence), `synthesize_article` retries synthesis once before dropping the
chunk. (2) Light crossfade: `_fade_out_tail` applies a 100 ms linear fade-out
to each chunk's tail before the silence gap, smoothing the voiced→silence
transition. (3) Read cache: `library.find_cached(url, mode, voice, llm_model)`
checks for an existing WAV before the pipeline runs; on hit the server sends
`done` immediately. New `llm_model` column on the `reads` table (auto-migrated)
+ composite index `idx_reads_cache`.

**Verified.** 59 pytest pass (new tests: `test_speak.py` for fade-out + retry,
`test_library.py` cache lookup — hit, miss by voice/model, miss on deleted WAV).

---

## 2026-06-20 — OCR config → its own `ocr:` section

**Status: done** — branch `llm-migration`. Moved the OCR vision model out of
`llm:` into a dedicated top-level `ocr:` block (different job from the summary
LLM). `LLMConfig{model}` + new `OcrConfig{model}`; `Config.load()` auto-migrates
an old `llm.vision_model` → `ocr.model`. The OCR model id is now threaded
explicitly through `_ocr_via_mlx` / `fetch_article` / `fetch_multi_page`
(`vision_model` arg) and `list_models(cfg.llm, cfg.ocr.model)`; the read job's
`/vision` switch mutates `cfg.ocr.model`. **Wire protocol unchanged** — the field
stays `vision_model` (WS read, `/api/config`) / `current_vision` (`/api/models`),
so the CLI needed zero changes. config.yaml restructured.

**Verified.** 49 pytest pass; migration test (old `llm.vision_model` → `ocr.model`);
FastAPI TestClient confirms `vision_model`/`current_vision`; real OCR through
`fetch_article(..., cfg.ocr.model)` returns clean text. Docs synced.

---

## 2026-06-20 — `/vision` switch (per-read OCR model picker)

**Status: done** — branch `llm-migration`. A CLI `/vision` command mirrors
`/model` but for the image/book OCR model, so OCR quality is switchable per-read
(light 3B for a quick snapshot, 7B for dense scans) instead of config-only.

**What shipped.** Server: `read` accepts `vision_model` (validated vs downloaded
models, mutates `cfg.llm.vision_model` in place; read job scans installed once if
either `model` or `vision_model` changed); `/api/config` + WS `config` carry
`vision_model`; `/api/models` carries `current_vision` (every model already
tagged `chat`/`vision`). CLI: `/vision [name]` via a shared `handlePickModel(kind)`;
`ModelList` gained a `kind` prop (filters chat vs vision, no recommendation marker
for vision); `vision_model` flows through `ws.read(...)`; pref `visionModel`
persists to `~/.readback/cli.json`; `/help` + KNOWN_COMMANDS updated. `/model` now
lists chat-only, `/vision` vision-only.

**Verified.** `tsc --noEmit` clean, `bun build` compiles, 49 pytest pass, FastAPI
TestClient confirms `vision_model`/`current_vision` on the REST surface and the
chat/vision split. Not yet driven end-to-end against a real image (mirrors the
proven `/model` path). Follow-up: auto-pick OCR model by source (ROADMAP).

---

## 2026-06-20 — Summary-LLM model experiments (quality/accuracy backlog)

**Status: proposed** — a shortlist of MLX models to trial for Summary mode, now
that the LLM is no longer the bottleneck (chain-of-thought disabled, ~4 s
summaries). Goal: find the best faithfulness/prose vs speed point for article +
book-scan summarization. No code change — `/model` already switches per-read; this
is a download-and-compare exercise. Default stays `Qwen3.5-9B-4bit`.

### Context

Target hardware: M5 Pro, 48 GB unified. CSM-1B (~6 GB) is always resident, so the
practical LLM budget is ~30 GB to stay comfortable (≤50% fit), ~36 GB before it
gets tight. 4-bit MLX builds (`mlx-community/*`) only. Quality for this task =
faithful, well-ordered spoken prose under the ~250-word ceiling — instruction
-following and grounding matter more than raw size past ~9B.

### Candidates (summary LLM)

| model | ~size | why try it | verdict for 48 GB |
|---|---|---|---|
| `Qwen3.5-9B-4bit` (current) | 5.5 GB | strong baseline, fast | keep as default |
| `Qwen3-30B-A3B-4bit` (MoE) | ~17 GB | near-32B quality, only ~3B active → fast; best "quality+speed" bet | **top experiment** |
| `Qwen2.5-32B-Instruct-4bit` | ~18 GB | dense/technical faithfulness upgrade | good fit, ~2-3× slower |
| `gemma-2-27b-it-4bit` | ~16 GB | excellent natural narration/prose for read-aloud | good fit |
| `Mistral-Small-3.1-24B-Instruct-4bit` | ~13 GB | efficient, strong instruction-following | good fit, lighter |
| `Phi-4-14B-4bit` | ~8 GB | reasoning-dense at small size; modest step up from 9B | comfortable |
| `c4ai-command-r-08-2024-4bit` (Cohere) | ~20 GB | **purpose-built for grounded summarization/RAG** — most on-task for faithfulness | good fit; ⚠ non-commercial license (OK for personal use) |
| `glm-4-9b-chat-4bit` (Zhipu) | ~5-6 GB | same-weight-class alternative to the Qwen default — cheap A/B sanity check | comfortable |
| `Llama-3.3-70B-Instruct-4bit` | ~40 GB | ceiling quality | ⚠ tight alongside CSM — edge of envelope, expect swap pressure |

⚠ **Avoid reasoning-first families** (DeepSeek-R1 distills etc.) — they emit
chain-of-thought by design and many ignore the off-switch, fighting the
`enable_thinking=False` fix that makes Summary mode fast/clean.
⚠ Exact `mlx-community/*` tags drift — verify the repo exists on HF before download.

### Candidate (vision OCR, separate `cfg.vision_model`)

| model | ~size | why try it |
|---|---|---|
| `Qwen2.5-VL-7B-Instruct-4bit` | ~5 GB | OCR-accuracy upgrade over the default 3B for dense/low-quality book scans |

### How to evaluate

1. `huggingface-cli download <id>` (or let the first `/model` switch pull it).
2. Read one representative URL article AND one multi-page book scan through each
   model in Summary mode, same voice/tone.
3. Compare on: faithfulness (no invented facts), ordering/coverage, prose
   naturalness when spoken, and the server's `summarize` timing (already logged).
4. Promote the winner to `config.yaml`'s `llm.model` default if it beats the 9B
   on quality without an unacceptable speed hit.

### Out of scope

- Auto-selecting a model by source length/type (manual `/model` for now).
- Any change to the fit heuristic or picker UI.

---

## 2026-06-20 — Replace Ollama with mlx-lm + mlx-vlm (full MLX LLM stack)

**Status: done** — branch `llm-migration`, v4.0.0. Removed Ollama entirely; summary/title/OCR all run in-process via mlx-lm + mlx-vlm on Apple's MLX framework, unifying with CSM-1B. `OllamaConfig` → `LLMConfig`, config key `ollama:` → `llm:` (old key auto-migrated), `ollama` dep replaced by `mlx-lm` + `mlx-vlm`. Model discovery scans HF cache. Non-chat models (whisper, parakeet, CSM, TTS) filtered from `/model` picker. Smoke-tested: Full + Summary mode end-to-end. All docs updated. 49 tests pass.

### Context

Ollama wraps llama.cpp behind a daemon — ~15–20% overhead vs raw inference, requires a separate background process, and is a different framework from the CSM-1B TTS engine (which already runs on MLX). Replacing it with `mlx-lm` (text generation) and `mlx-vlm` (vision/OCR) means:
- **+25–30% generation speed** (~100 tok/s vs ~78 tok/s on a 7B 4-bit model, M5 Pro).
- **No daemon** — in-process calls, no `ollama serve` requirement.
- **Framework alignment** — both LLM and TTS share MLX/Metal unified memory, avoiding the Ollama↔MLX memory fragmentation.
- **One fewer system dependency** for setup.

The current Ollama surface is contained: `LLMClient.oneshot()` (summary + title gen), `pick_vision_model` + `_ocr_via_ollama` (image OCR), and model listing for the CLI `/model` picker.

Trade-off: MLX models are HuggingFace safetensors (not GGUF) — a one-time ~4.5 GB download per model. Existing Ollama blobs can't be reused. Model discovery changes from querying a server API to scanning the local HF cache.

### Design

1. **Config** — rename `OllamaConfig` → `LLMConfig`. Fields: `model: str` (HF ID, default `mlx-community/Qwen3.5-9B-4bit`), `vision_model: str` (HF ID, default `mlx-community/Qwen2.5-VL-3B-Instruct-4bit`). Drop `host` (no server). Top-level key stays `ollama` in `config.yaml` for now → renamed to `llm` (breaking config change, but minor — only one user).

2. **`llm/client.py`** — replace `ollama.Client.chat()` with `mlx_lm.load()` + `mlx_lm.generate()`. The model + tokenizer are loaded lazily on first call (like CSM). Chat template applied via `tokenizer.apply_chat_template()`. `_ThinkStripper` stays (belt-and-suspenders for Qwen3.5 models). `temperature` and `top_k` passed to `generate()`. Model swap = unload current + load new (heavier than Ollama's server-side swap, but infrequent — `/model` is a per-session action).

3. **`llm/models.py`** — replace Ollama API calls with HF cache scanning. `list_models()` scans `~/.cache/huggingface/hub/models--mlx-community--*` for downloaded MLX models, reads their `config.json` for parameter count, computes RAM-fit verdicts (same heuristic). `pick_vision_model()` replaced by a config-driven default (`cfg.vision_model`). `installed_model_names()` returns HF IDs of downloaded models.

4. **`pipeline/extract.py`** — `_ocr_via_ollama` → `_ocr_via_mlx`. Uses `mlx_vlm.load()` + `mlx_vlm.generate()` with the vision model. Image passed as a local file path (mlx-vlm supports this natively). The vision model is loaded lazily and cached (same pattern as the text LLM). `pick_vision_model` calls removed — the vision model is config-driven.

5. **`server/server.py`** — wire `cfg.llm` (renamed from `cfg.ollama`). Model swap logic updated: validate against downloaded models, then trigger unload/reload on `LLMClient`. `ReaderModels.ensure_loaded` loads the text LLM alongside CSM (vision model loads lazily on first OCR).

6. **Thread safety** — the pipeline is sequential (fetch → summarize → synthesize), so the text LLM and CSM never run concurrently. The LLM runs via `asyncio.to_thread` (same as today's Ollama calls). Both models share unified memory (~4.5 GB LLM + ~2 GB CSM = ~6.5 GB of 48 GB — comfortable). No shared MLX executor needed — they're separate models on separate threads at separate times.

7. **Dependencies** — `pyproject.toml`: replace `ollama>=0.6.0` with `mlx-lm` + `mlx-vlm`. Both are lazy imports in the modules that use them (same pattern as `csm-mlx`), so the Pi server boots without them. `requirements-pi.txt`: remove `ollama` (Pi never runs LLM/OCR).

8. **`config.yaml`** — update the `ollama:` block to `llm:` with new defaults. `setup.sh` updated: instead of pulling an Ollama model, pre-download the default MLX model via `huggingface-cli download mlx-community/Qwen3.5-9B-4bit`.

9. **CLI `/model` picker** — the list now shows downloaded MLX models (HF IDs) instead of Ollama model names. The recommendation logic (largest good-fit chat model) stays. Vision models filtered out. The display adapts: HF IDs are longer, so show a short alias (e.g. `Qwen3.5-9B-4bit` from `mlx-community/Qwen3.5-9B-4bit`).

### Files

- `src/readback/config.py` (modified): `OllamaConfig` → `LLMConfig`, new fields
- `src/readback/llm/client.py` (modified): mlx-lm load/generate, lazy model management
- `src/readback/llm/models.py` (modified): HF cache scanning, drop Ollama API calls
- `src/readback/pipeline/extract.py` (modified): `_ocr_via_mlx` replacing `_ocr_via_ollama`
- `src/readback/server/server.py` (modified): wire `cfg.llm`, model swap, ensure_loaded
- `src/readback/__main__.py` (modified): `cfg.ollama` → `cfg.llm`
- `pyproject.toml` (modified): swap deps
- `requirements-pi.txt` (modified): remove `ollama`
- `config.yaml` (modified): `ollama:` → `llm:` block
- `scripts/setup.sh` (modified): HF download instead of ollama pull

### Out of scope

- Parallel map-reduce (sequential for now — same as Ollama era)
- LLM LoRA fine-tuning via mlx-lm (capability exists but not wired)
- Batched/concurrent LLM+TTS (pipeline stays sequential)
- Ollama fallback/compatibility mode (hard cut)
- New CLI commands or protocol changes (transparent swap)
- Dashboard changes (it doesn't touch the LLM)

### Verification

1. `pip install -e .` succeeds with mlx-lm + mlx-vlm deps, no ollama dep
2. `readback` starts — no Ollama process needed; `GET /api/config` responds
3. Paste a URL, Summary mode → LLM summarizes via mlx-lm, audio plays (quality parity with Ollama)
4. Paste a URL, Full mode → unchanged (no LLM involved)
5. Drop an image path → OCR via mlx-vlm, text extracted, audio plays
6. Folder of images → multi-page OCR via mlx-vlm, map-reduce summary works
7. `/model` → lists downloaded MLX models with RAM-fit verdicts + recommendation
8. `/model mlx-community/Qwen3.5-4B-4bit` → switches model, next summary uses it
9. `grep -r "ollama" src/readback/` → zero hits (full removal)
10. Pi: `pip install -r requirements-pi.txt` succeeds without mlx-lm/mlx-vlm; server boots, dashboard works
11. `pytest` → existing tests pass (no MLX in the test suite)

---

## 2026-06-20 — Design system consistency pass

**Status: done** — branch `design-revamp`. Established a shared design token
layer (`src/design-system/tokens/`) as the canonical source for the Ghost palette,
type scale, spacing, and motion values. Dashboard CSS now imports from the token
files; landing page inlines the same values (deployed standalone). All raw px
`font-size` values replaced with `var(--text-*)` tokens across both surfaces; play
button size standardized to `var(--control-h)` (40px); inline `rgba()` accent fills
replaced with semantic tint tokens (`--accent-08`, `--accent-14`, `--accent-28`);
status tints (`--green-10`, `--yellow-10`, `--red-10`) added. Dashboard build
verified clean.

---

## 2026-06-17 — Source-aware tones (article vs book)

**Status: done** — branch `feat/cli-cache`. Auto-pick a reading *tone* from the source type: a URL reads as a blog/article, an image/folder reads as a book. A tone bundles a summary framing **and** a TTS delivery temperature. Fully automatic — no new commands or config. Shipped as planned: new `pipeline/tones.py` (`ARTICLE` 0.8 / `BOOK` 0.6 + `tone_for`), `classify_source` + `_book_title_from_text` in `extract.py`, `system` param threaded through `summarize_article`/`_map_reduce`, `set_temperature` on `Synthesizer`+`CsmEngine`, server computes `tone_for(classify_source(url))` and wires the prompt + temperature. 49 tests green (`test_tones.py` covers classify + mapping); fake-LLM smoke confirms book sources get the book framing + 0.6.

### Context

Everything currently reads with one summary prompt + one TTS temperature. But a blog and a scanned book want different treatment: a book passage should open by naming its chapter/topic and be narrated in a measured voice; an article wants a livelier explainer. The source already tells us which: URLs are articles, scanned images are (mostly) books.

### Design

1. **`pipeline/tones.py`** (new): a frozen `Tone` dataclass `{name, summary_system, temperature}` and two instances:
   - `ARTICLE` — the existing spoken-explainer prompt, `temperature 0.8` (livelier).
   - `BOOK` — a new "narrate this book passage; open by naming the chapter or topic, then explain faithfully" prompt, `temperature 0.6` (measured/composed).
   `tone_for(kind: str) -> Tone` maps `"book"` → BOOK, else ARTICLE. (Room for a 3rd tone — e.g. `PAPER` — later.)
2. **`extract.py`**: `classify_source(source) -> "book" | "article"` (image suffix or folder/glob → book; else article). For book sources, derive the title from the **first ~3 OCR lines** via a focused `oneshot` (`_book_title_from_text` — "identify the chapter or topic, max 8 words"), replacing the generic `_title_from_text`. The detected chapter/topic flows into the summary as the article title, so the BOOK prompt leads with it.
3. **`summarize.py`**: `summarize_article(..., system: str | None = None)` — defaults to the ARTICLE prompt for back-compat; threads `system` into `_summarize_once` and the map-reduce **reduce** step. The map-step condensation prompt (`_MAP_SYSTEM`) stays tone-agnostic. (The existing `_SUMMARY_SYSTEM` moves to `tones.py` as `ARTICLE.summary_system`.)
4. **`synthesizer.py` / `csm_engine.py`**: `Synthesizer.set_temperature(temp)` → engine sets `self.cfg.temperature` (read fresh by `_make_sampler` on the next synth). Plain attribute set; reads are serialized so it's safe.
5. **`server.py`**: compute `kind = classify_source(url)` once; `tone = tone_for(kind)`. Pass `tone.summary_system` to `summarize_article`; call `synth.set_temperature(tone.temperature)` before synth. The user's `/voice` choice is untouched — tone varies delivery (temperature), not which voice.

### Files

- `src/readback/pipeline/tones.py` (new): `Tone`, `ARTICLE`, `BOOK`, `tone_for`
- `src/readback/pipeline/extract.py` (modified): `classify_source`, `_book_title_from_text`, book sources use it
- `src/readback/pipeline/summarize.py` (modified): `system` param; `_SUMMARY_SYSTEM` → `tones.ARTICLE.summary_system`
- `src/readback/tts/synthesizer.py` + `tts/csm_engine.py` (modified): `set_temperature`
- `src/readback/server/server.py` (modified): classify → tone → wire summary prompt + temperature
- `tests/test_tones.py` (new): `classify_source` + `tone_for` mapping (pure logic)

### Out of scope

- `/tone` manual override + persisted pref (auto-only for now, per decision)
- A 3rd tone (paper/news) — structure leaves room; not built yet
- Per-tone voice swap (delivery varies by temperature only; user's voice stays)
- CLI/protocol surfacing of the active tone (no `done`-payload change)
- Configurable tone temps/prompts in `config.yaml`

### Verification

1. Paste a URL, summary mode → article prompt + temp 0.8; reads as a lively explainer
2. Paste a book-page image, summary mode → title is the chapter/topic from the first lines; summary opens by naming it; temp 0.6 (measured)
3. Folder of pages, summary mode → same book tone over the stitched document
4. Full mode (URL or book) → temperature still set by tone; text unchanged (verbatim)
5. `/voice` still controls the voice in both tones (tone only shifts temperature)
6. `pytest tests/test_tones.py` → `classify_source` + `tone_for` map correctly

---

## 2026-06-17 — Map-reduce summarization (long docs / book scans)

**Status: done** — branch `feat/cli-cache`. Summary mode no longer truncates long inputs at `summary_max_chars`; it map-reduces them so a whole book scan summarizes end-to-end.

### Context

Multi-page (book scan) shipped as one continuous document, but Summary mode still fed it through a single `oneshot` truncated to `summary_max_chars` (16000 ≈ 10-12 pages) — the tail was silently dropped. A 30-page scan lost two-thirds of its content. Fix: when the body exceeds `max_chars`, split → summarize each batch (map) → combine the digests into the final spoken explanation (reduce), recursing if the combined digests are themselves still too long.

### Design

1. **`_batches(text, max_chars)`** in `summarize.py`: greedily packs paragraphs (split on `\n{2,}`) into ≤`max_chars` batches; an over-long paragraph falls back to sentence split (`(?<=[.!?])\s+`); an over-long single sentence is hard-cut. Pure logic — unit tested.
2. **`_summarize_once(llm, title, body)`**: the existing single-`oneshot` spoken-explanation path, factored out. Used for short articles AND the final reduce.
3. **`_MAP_SYSTEM`** prompt: faithful prose condensation of one section (no meta framing, no invented facts) — intermediate digests, not the final voice.
4. **`summarize_article`**: if `len(body) <= max_chars` → `_summarize_once` (unchanged fast path). Else map-reduce: map each batch with `_MAP_SYSTEM`, join digests, reduce with `_SUMMARY_SYSTEM` via `_summarize_once`; if joined digests still exceed `max_chars`, recurse (depth-limited to 3).
5. **Progress**: optional `progress(done, total)` callback fired during the map phase; the server reports `summarizing section N / M` over the existing `phase` WS channel (mirrors multi-page OCR progress). No protocol change.

### Files

- `src/readback/pipeline/summarize.py` (modified): `_batches`, `_summarize_once`, `_MAP_SYSTEM`, map-reduce `summarize_article` with optional progress
- `src/readback/server/server.py` (modified): pass a `summarizing section N / M` progress callback into `summarize_article`
- `tests/test_summarize_batches.py` (new): `_batches` packing / fallback / hard-cut coverage

### Out of scope

- Parallelizing the map calls (sequential for now — Ollama single-stream simplicity)
- Configurable batch size (reuses `summary_max_chars`)
- Map-reduce for Full mode (Full has no LLM step — reads verbatim)

### Verification

1. Short article (< 16k chars), summary mode → exactly one LLM call, identical output to before (fast path)
2. 30-page book scan, summary mode → phases show `summarizing section 1 / N …`, final audio is a cohesive summary covering the whole book (not just the first ~12 pages)
3. `pytest tests/test_summarize_batches.py` → packing respects `max_chars`, splits on paragraph then sentence, hard-cuts a giant sentence
4. Full mode on the same scan → unaffected (reads everything verbatim, no LLM)

---

## 2026-06-17 — Multi-page image input (folder / glob)

**Status: done** — branch `feat/cli-cache`. Folder or glob → sorted pages → OCR each → **one continuous document** → normal full/summary pipeline.

> **Shipped differently from the original chapter design below.** The "each image = a chapter, summarize per chapter, spoken Chapter-N headers" model was wrong for the actual use case (reading **book scans**): a photo is a *page*, not a chapter, so per-page summaries shred the narrative and the headers are meaningless. Final design: OCR pages in natural order, stitch into **one continuous document** (single space at each page seam so sentences flow across page breaks), and feed it through the **same** summarize/full step as a URL article — no per-page LLM calls, no synthetic headers. The vision model is resolved **once** per batch (not per image — `pick_vision_model` does a `client.show()` per installed model, which was the multi-page slowdown). `fetch_multi_page(source, ollama_cfg, progress_cb)` no longer takes `mode`/`llm`; the server runs step 2 uniformly. `_num_to_word` was removed (no chapter headers). Long scans truncate at `summary_max_chars` — map-reduce summarization for whole books is a follow-up. Progress phase text is `reading page N / M`.

### Context

Single-image OCR shipped. Natural next step: scanned books, multi-page documents, screenshot sequences. A folder of PNGs or a glob (`page*.png`) should be treated as an ordered sequence of chapters, with the existing pipeline (TTS → WAV) consuming the assembled text unchanged.

### Design

1. **`_is_multi_page(source)`** in `extract.py`: returns True if source ends with `/`, is an existing directory, or contains `*`/`?` glob metacharacters.

2. **`_collect_images(source)`**: resolves the source to a sorted list of image paths. Directory → `glob("*")` filtered to `_IMAGE_EXTS`. Glob string → `glob.glob(source, recursive=False)` filtered to `_IMAGE_EXTS`. Both sorted with `_natural_sort_key` (splits on digit runs: `page1 < page2 < page10`). Raises `ExtractError` if no images found.

3. **`fetch_multi_page(source, mode, ollama_cfg, llm=None)`** in `extract.py`: new function. Calls `_collect_images`, OCRs each via `_ocr_via_ollama`, then:
   - **full mode**: joins chapters as `"Chapter 1\n\n{text}\n\nChapter 2\n\n{text}…"` → single Article. Title from `_title_from_text` on the first chapter's text (fast, representative).
   - **summary mode**: calls `llm.oneshot` per chapter with the existing `_SUMMARY_SYSTEM` prompt (imported from `summarize.py`), prefixes each summary with `"Chapter one. / Chapter two. …"` (word form for natural TTS), stitches summaries → single Article. Overall title from `_title_from_text` on the stitched summaries.
   - Progress is signalled via a `progress_cb(page_index, total)` optional callback so the server can send WS phase messages.

4. **`server.py`** step 1 branch: import `_is_multi_page`, `fetch_multi_page`. If source is multi-page: send phase `"fetching page 1 / N"` updates via the `progress_cb`, call `fetch_multi_page(url, mode, cfg.ollama, llm)`, then **skip step 2** (summarization already done inside). If single source: existing path unchanged.

5. **`app.tsx` CLI validation**: extend the local-path carve-out to also allow:
   - Paths with a `/` after position 0 (multi-segment = never a slash command)
   - Strings containing `*` or `?` (glob)
   Both bypass the slash-command guard and URL check.

6. **Number-to-word helper** `_num_to_word(n)` for chapter headers in summary mode — covers 1–20 with a numeric fallback (`"chapter 21"`). Keeps TTS from reading "Chapter 1" as "Chapter one" inconsistently.

### Files

- `src/readback/pipeline/extract.py` (modified): `_is_multi_page`, `_collect_images`, `_natural_sort_key`, `_num_to_word`, `fetch_multi_page`
- `src/readback/server/server.py` (modified): multi-page branch before step 1, per-page phase messages, skip summarization for multi-page
- `src/cli/src/app.tsx` (modified): extend local-path detection for directories and globs

### Out of scope

- Recursive directory scanning (one level only)
- PDF input (separate feature)
- Per-chapter WAV files or chapter seek points
- Dashboard UI for multi-page reads (shows as one entry like any read)
- Config for images-per-chapter grouping (always 1 image = 1 chapter)

### Verification

1. `~/Desktop/scan/` (folder with 3 PNGs, full mode) → phases show "fetching page 1 / 3" … → audio reads all three chapters verbatim in order
2. Same folder, summary mode → audio reads "Chapter one. [summary]. Chapter two. [summary]. Chapter three. [summary]."
3. Glob `~/Desktop/page*.png` (full mode) → natural-sorted, same result as folder
4. Folder with mixed files (`.png` + `.DS_Store` + `.txt`) → only images processed, others silently skipped
5. Empty folder → `ExtractError` "no images found"
6. Single image path still works unchanged
7. URL still works unchanged

---

## 2026-06-17 — Image OCR via Ollama vision

**Status: done** — branch `feat/image-ocr`. Drop an image path into the CLI input → Ollama vision model extracts the text → reads it aloud. No new model pulls needed (`qwen3.5:4b`, `gemma4:12b`, `gemma4:e4b`, `gemma4:26b` all have vision already).

### Context

Users want to read text from screenshots, photos, or scanned pages. All Gemma 4 and Qwen 3.5 models already installed have the `vision` capability in Ollama. The existing Ollama integration (`llm/client.py`) is one `images=` kwarg away from vision support. The full pipeline (chunk → TTS → play) is unchanged — OCR just replaces the URL fetch step.

### Design

1. **`llm/models.py` — `pick_vision_model(cfg)`**: calls `ollama.Client.show(name)` for each installed model to check `capabilities`, returns the name of the smallest good-fit vision model. Preference order: `qwen3.5:4b` → `gemma4:12b` → `gemma4:e4b` → `gemma4:26b` → first vision model found → `None`.

2. **`pipeline/extract.py` — image branch**: add `_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".heic", ".webp", ".tiff", ".bmp"}`, `_is_image_path(s)`, and `_ocr_via_ollama(path, ollama_cfg)` (base64-encodes the file, sends to the vision model with prompt "Extract all text from this image verbatim. Output only the text."). `fetch_article` gains an optional `ollama_cfg: OllamaConfig | None = None` param; if source has an image extension it routes to `_ocr_via_ollama` and uses the filename stem as the title. URL path is unchanged.

3. **`server/server.py`**: pass `cfg.ollama` as `ollama_cfg` kwarg to `fetch_article`. Update "Please enter a URL." error → "Please enter a URL or image path.". Phase label stays `"fetching"` (covers both cases fine).

4. **`src/cli/src/app.tsx` — `handleSubmit`**: before the slash-command guard, check if value ends with an image extension (`/\.(png|jpg|jpeg|heic|webp|tiff|tif|bmp)$/i`) — if so, skip the command check and validate it as a file source. Update the URL-only error message to mention image paths. Tilde paths (`~/…`) bypass the slash guard already.

### Files

- `src/readback/llm/models.py` (modified): add `pick_vision_model(cfg) -> str | None`
- `src/readback/pipeline/extract.py` (modified): add image detection + `_ocr_via_ollama`, optional `ollama_cfg` param on `fetch_article`
- `src/readback/server/server.py` (modified): pass `ollama_cfg` to `fetch_article`, update error text
- `src/cli/src/app.tsx` (modified): handle image paths before slash-command guard, update error message

### Out of scope

- PDF / text file extraction (separate feature)
- Drag-and-drop (terminal limitation)
- Progress during OCR (single Ollama call, not chunked)
- Dashboard image preview
- Config knob for the OCR model (always auto-picks best available vision model)

### Verification

1. Drop `~/Desktop/screenshot.png` into the CLI → phases show `fetching` → `synthesizing` → audio plays with the extracted text
2. Drop an absolute path `/Users/mks/…/image.jpg` → same result
3. Drop a URL → original URL path unaffected
4. No vision model available (hypothetical) → clear `ExtractError` "no vision-capable model found in Ollama"
5. Unsupported extension `.gif` → falls through to URL path → "doesn't look like a URL or image path"

---

## 2026-06-17 — CLI library screen

**Status: done** — branch `feat/cli-cache`. CLI-only; no Python/server/protocol changes.

### What shipped

`/library` (alias `/lib`) opens a new `library` screen in the terminal: paginated list of past reads (newest first, 20 per page), arrow-key cursor, `▸` indicator, truncated titles with mode/duration/date columns. Enter constructs a `DoneMsg` from the library item and calls `resolveWav` + `player.play` — drops straight into the existing `PlayerView`. `d` twice to delete (first press shows an inline confirmation; second calls `DELETE /api/library/{id}` and removes the row from local state). `n` loads the next page. `esc` returns to input.

`q` on the URL input screen (when the field is empty) now triggers quit. Intercepted in `UrlInput.onChange` before the controlled `TextInput` value updates. Quit path: `dispatch("quitting")` → new `quitting` screen renders a braille spinner (`⠋…⠏`) for 300 ms → `shutdown()` + `exit()`.

New files: `src/cli/src/components/LibraryView.tsx`. Modified: `src/cli/src/app.tsx`, `src/cli/src/components/UrlInput.tsx`. Version bumped to v3.4.0.

### Verified

TypeScript (`bun tsc --noEmit`) clean. Functional verification: `/library` opens list, Enter replays, `d d` deletes, `esc` returns, `q` shows quitting spinner and exits.

---

## 2026-06-15 — Landing-page sync: "run it on your network"

**Status: done** — branch `deployment`. Surface the shipped Pi / home-network deployment on the marketing site without breaking its hook-and-redirect shape.

### Design

Pure copy + redirect, no new images (per request — the README Pi-deployment section already carries the mobile screenshots).

1. **Features** (`.feat-term`) — add a 6th line `network`: "Run it on your network — deploy the dashboard to a Raspberry Pi (built on my [PiZoW](https://github.com/MKS-01/pizow) setup) and replay from any device at home." Bumped the footer count 5 → 6, extended the `.feat-term` `aria-label`, and added the `:nth-child(6)` stagger rule in `style.css`.
2. **Dive in** (`.dive`) — new redirect button "Run it on a Pi ↗" → `README#pi-deployment`.
3. Hero / Hear it / See it work left untouched — the on-device pitch still holds.

Reviewed via local headless screenshot before push. Deploys on merge to `main` (Pages workflow); no `pages.yml` change needed (no new media referenced).

## 2026-06-15 — Pi deployment: library dashboard + audio sync

**Status: done** — branch `deployment`. Deploy readback library REST + dashboard to a Raspberry Pi as a network-accessible read-history viewer. Mac stays the generation host (CSM-1B + Ollama); Pi is display/playback only.

### Context

CSM-1B (MLX/Metal) and Ollama are Apple Silicon–only. Pi serves the FastAPI library REST endpoints, the Vue dashboard (static `dist/`), and WAV files rsynced from Mac. A sync script pushes audio + DB on demand. The `../readback-audio-db/` relative paths in `config.yaml` resolve correctly on Pi (same directory layout as Mac).

### Design

1. **No server.py changes** — all mlx/csm-mlx imports in `csm_engine.py` are lazy (inside function bodies), so the server starts on Pi without csm-mlx installed. TTS only fails if a read job is triggered, which Pi never does.
2. **`requirements-pi.txt`** — all pyproject.toml deps except `csm-mlx` (MLX is Apple Silicon only).
3. **`.env.example`** — documents `PI_USER`, `PI_HOST`, `PI_PATH`, `PI_AUDIO_DIR`, `PI_DB_PATH`, `PI_PORT`.
4. **`config.pi.example.yaml`** — Pi-safe config template: built-in speaker (no wav), same relative reader paths as Mac (resolve to `~/readback-audio-db/`). Deploy script copies on first deploy only.
5. **`scripts/deploy-pi.sh`** — build dashboard → rsync source + dist → venv + pip → PM2 start/restart. `config.yaml` on Pi is never overwritten after first deploy.
6. **`scripts/sync-pi.sh`** — stop Pi server → rsync audio + DB → restart. Stops server to avoid SQLite lock during DB copy.
7. **PYTHONPATH** — `PYTHONPATH=${PI_PATH}/src` set before PM2 start (captured in PM2's saved env); `--update-env` on restart picks up changes.

### Files

- `requirements-pi.txt` (new): Pi deps, no csm-mlx
- `.env.example` (new): Pi connection + path template
- `config.pi.example.yaml` (new): Pi config template
- `scripts/deploy-pi.sh` (new): build + rsync + PM2 deploy
- `scripts/sync-pi.sh` (new): rsync audio + DB Mac → Pi

### Out of scope

- Nginx / reverse proxy / SSL
- Auto-sync on new read
- Two-way sync (Pi → Mac)
- `--remote` mode (git pull on Pi)
- Pi initial OS / SSH key setup (assumed working)
- Running TTS or Ollama on Pi

### Verification

1. `cp .env.example .env` → fill in PI_USER, PI_HOST, PI_PATH
2. `bash scripts/deploy-pi.sh` → completes; `pm2 list` shows `readback` online
3. `curl http://<PI_HOST>:8080/api/config` → returns JSON
4. Open `http://<PI_HOST>:8080` → dashboard loads
5. `bash scripts/sync-pi.sh` → audio + DB rsynced
6. Refresh dashboard → past reads appear, audio plays in browser
7. Pi reboot → `pm2 startup && pm2 save` (run once manually on Pi)

---

## 2026-06-14 — Landing page layout rework (de-box + catchier hero)

**Status: done** — branch `feat/animations`. The page read as a rigid stack
of bordered rectangles; rework it to structure with whitespace + typography +
a couple of intentional surfaces (per `emil-design-eng`: "beauty is leverage",
reduce noise, cohesion). User-approved direction: bold rework.

### Design

1. **De-box.** Drop most `1px` borders. Sections separate with air + a single
   **hairline rule under each `##` header**, not a full box. Keep only two framed
   surfaces — the **screenshot viewer** (`.demo-frame`) and the **`--features`
   terminal** (`.feat-term`) — since those genuinely are screens/terminals.
2. **Sample player** — borderless; the waveform floats on the page (play button
   keeps its accent outline since it's a control).
3. **Step rail → underline tabs.** `.demo-steps`/`.demo-step` lose the boxed
   panel; active step = accent text + accent underline on a shared baseline rule.
   The rAF progress bar (`#demo-progress`) stays (timing), JS untouched.
4. **Hero.** Kicker above the wordmark: `// a weekend project · built with Claude
   Code` (Martian Mono). Tagline → **"Your reading list, read to you."** (USP +
   the name: readback = read back to you); pitch → "A natural neural voice reads
   whole articles aloud — right in your terminal, entirely on-device. Nothing
   leaves your Mac." Copy mined from docs/JOURNEY.md, not generic.
5. **Rhythm.** More vertical air; bigger `##` headers; hero stays centered, content
   sections left-aligned (incl. the Dive-in CTA) for variety vs the all-centered
   monotone.
6. **Animation** — keep everything (ease-out curves, stagger, stepper progress,
   reduced-motion); just re-apply to the new structure.
7. **Softer corners + no `##`.** Sharp box corners read harsh, and the `##`
   header prefix looked like broken markdown to non-tech viewers. Added
   `--radius: 8px` on buttons/frames/panels (rounded-square sample play button,
   4px on inline code), and dropped the `##` spans from all `h2`s (the hairline
   rule already separates them). The **dashboard** got the same `--radius: 8px`
   for cohesion — search box, sort toggle, the cards panel (+ `overflow:hidden`),
   play + skip buttons, load-more.

### Files

- `src/landing-page/index.html` — hero kicker + new copy; step-rail markup stays.
- `src/landing-page/style.css` — de-box, hairline headers, underline tabs,
  left-align, hero kicker, spacing.

### Out of scope

- Section content/order changes beyond the hero copy (order stays hook-first).
- New media; dashboard; the repo docs.

### Verification

1. Headless screenshot: few/no full-box borders; hairline under each header;
   underline tabs; borderless player; kicker + new tagline render.
2. CDP: stepper progress still fills; `:focus-visible` rings intact;
   reduced-motion keeps opacity, drops movement.
3. Mobile width renders without overflow.

---

## 2026-06-14 — Emil re-review fixes + landing-page design pass + content trim

**Status: done** — branch `feat/animations`. After installing the real
`emil-design-eng` skill (`.agents/skills/`), re-audited the animation pass against
its actual guidance, applied the fixes to both surfaces, did a focused
design-engineering polish on the landing page (within its terminal identity), and
trimmed the page to a hook-and-redirect shape.

**Content trim (added scope, user-approved):** the page was re-documenting the
whole project. Cut four sections that duplicate the repo/docs — **How it works**
(flow diagram), **Quick start** (install code), **How it took shape** (timeline),
**Architecture** (stack list) — and replaced them with one **Dive in** band of
GitHub links (Quick start / Architecture / Browse the repo). Kept the things you
can't get from a README scan: hero, **Hear it** (sample player), **See it work**
(screenshot stepper), Features. ~8 screens → ~4. Dead CSS/JS for the cut sections
removed; no `docs/media` files dropped so `pages.yml` is untouched.

**Features reformat:** the 2×2 card grid became a `readback --features` **terminal
listing** (`.feat-term`/`.feat-list`) — green ✓, accent-aligned key column, bold
claim + hang-indented detail, and a `5 features · 0 cloud calls · 0 API keys`
footer. Rows print-in (opacity stagger), footer fades last. More formal + on-brand.

Verified over CDP: sections are exactly `hero · sample · demo · features · dive ·
footer`; the stepper progress bar fills via rAF; `:focus-visible` rings render;
reduced-motion keeps opacity fades, drops movement.

### Context

The first animation pass (entry below) was built from general principles, not the
actual skill file (the public page is just a promo). With the skill installed, a
re-review surfaced concrete corrections; the user approved all of them and asked
for a fuller design pass on the landing page (animation included).

### Design — animation corrections (both surfaces)

1. **Drop the bounce.** `--spring: cubic-bezier(0.34,1.56,0.64,1)` had real
   overshoot; the skill reserves bounce for playful/drag. Replaced with Emil's
   exact curves: `--ease-out: cubic-bezier(0.23,1,0.32,1)` for entrances/press,
   `--ease-drawer: cubic-bezier(0.32,0.72,0,1)` for the dashboard accordion.
2. **Gate hover movement** behind `@media (hover: hover) and (pointer: fine)` —
   touch devices fire `:hover` on tap, leaving transforms stuck.
3. **Gentler reduced-motion** — "fewer and gentler, not zero": keep opacity/color
   fades (card fade, loading pulse, caret blink, scroll-reveal opacity), drop only
   movement (slide-in translate, height accordion, press scale, drift/sway/pulse).
4. **Tighten timing** — dashboard card entrance 400 → 280 ms (skill: UI < 300 ms).

### Design — landing-page polish (terminal identity kept)

5. **Hero** — soft radial accent glow behind the wordmark for depth; primary vs
   secondary CTA distinction; press states.
6. **"See it work" stepper** — a linear progress bar synced to the 4.5 s
   auto-advance (rAF-driven, freezes on hover) so the timing is legible.
7. **Detail polish** — `:focus-visible` rings, `::selection`, subtle scrollbar,
   gated feature-card hover lift, stack-row hover.

### Files

- `src/dashboard/src/styles.css` — curves, accordion easing, reduced-motion, timing.
- `src/landing-page/style.css` — curves + all of the above polish.
- `src/landing-page/index.html` — stepper progress element + rAF auto-advance refactor.

### Out of scope

- Dashboard visual redesign (animation fixes only).
- New page content/sections, copy rewrites, new screenshots.
- Any framework/library (still pure CSS + vanilla JS / Vue transitions).

### Verification

1. Dashboard rebuilds; CDP confirms no `--spring` left, accordion uses drawer curve,
   reduced-motion keeps card-fade opacity but zeroes transforms.
2. Landing page: hero glow renders; CTA primary/secondary read distinctly; stepper
   progress fills over 4.5 s and freezes on hover; `:focus-visible` rings show on tab.
3. Reduced-motion: scroll-reveal still fades (opacity), no translate/drift/sway/pulse;
   content never invisible.
4. Both pages render with no layout breakage (headless screenshot).

---

## 2026-06-14 — Animation pass: dashboard + landing page (Emil Kowalski style)

**Status: done** — branch `feat/animations`. Add purposeful, spring-eased animations to both surfaces: staggered list/section entrances, smooth player panel expand/collapse, delete exit, button micro-interactions, and better hero easing. Zero new dependencies.

**Implementation note:** the player accordion uses the CSS `grid-template-rows: 0fr↔1fr` trick via a `<Transition>` wrapper (`.player-panel`) rather than the JS height hooks in the original design — same UX, no `transitionend`/`done()` edge cases, and reduced-motion-safe for free. The `.player`'s top spacing moved from `margin-top` to `padding-top` so it's clipped during collapse. Verified end-to-end via Chrome DevTools Protocol: card `--i` stagger 0→8 (capped), `.player-panel` grid-rows mid-interpolation on play, button `transform` press wiring, and `prefers-reduced-motion` collapsing all durations to 0s with content forced visible (fixed a specificity bug where `.reveal .feat-grid li { opacity: 0 }` outranked the reduced-motion reset — now `!important` + full selector).

### Context

The landing page has a solid scroll-reveal base but uses flat `ease-out` everywhere and reveals entire sections without staggering children. The dashboard has almost no animation — no card entrance, no expand/collapse for the player that pops open when you click a card, no exit on delete. Emil Kowalski's approach: spring-like cubic-bezier for organic feel, stagger lists to show structure, animate expand/collapse with real heights (not `max-height` jumps), and keep micro-interactions (`:active` scale) on every interactive surface. Only animate things that carry meaning — not the search box, not the sort toggle.

### Design

**Both surfaces — shared principle:**
1. Add `--spring: cubic-bezier(0.34, 1.56, 0.64, 1)` (gentle overshoot) and `--ease-out: cubic-bezier(0.16, 1, 0.3, 1)` (snappy ease-out) as CSS variables. Replace flat `ease-out` usage.

**Landing page (`style.css` + `index.html`):**
2. Upgrade `@keyframes rise` easing to `--spring`; add `@keyframes fade-in` (opacity-only) for subtler elements.
3. **Button hover/press** — `.btn:hover { transform: translateY(-1px) }` + `.btn:active { transform: translateY(0) scale(0.98) }`.
4. **Stagger section children** — IntersectionObserver callback also adds staggered `--i` vars to direct children (feat-grid `li`, timeline `.tl-item`, stack-list `li`). Each child transitions `opacity + translateY` with `transition-delay: calc(var(--i) * 60ms)`.
5. **Demo caption fade** — add a CSS opacity transition on the caption element; JS briefly toggles a class to fade out before swapping text.
6. **Timeline dot pulse** — `.tl-item.cur .tl-dot` plays a single `scale(1) → 1.25 → 1` pulse on `.in`.

**Dashboard (`styles.css` + `App.vue` + `ReadCard.vue`):**
7. **Card list entrance** — `<TransitionGroup>` around cards. Each card gets `--i` inline style (capped at 8 to limit total delay). Enter: `opacity 0→1`, `translateY(8px)→0`, `transition-delay: calc(var(--i) * 40ms)`.
8. **Delete exit** — `TransitionGroup` leave: `opacity 1→0`, `translateX(-6px)`, 200ms.
9. **Player panel expand/collapse** — `<Transition>` with JS hooks (`onBeforeEnter` height 0, `onEnter` height scrollHeight, `onAfterEnter` height auto; reverse for leave). Real accordion, no `max-height` jump.
10. **Button press feedback** — `.play:active, .skips button:active, .load-more:active { transform: scale(0.95); }`.
11. **Active card accent border** — `transition: box-shadow 0.2s, background 0.2s` on `.card` so the `inset 2px 0 0 var(--accent)` slides in.
12. **Loading pulse** — `.muted` gets a `pulse` animation keyed to a `.loading` CSS class toggled while `loading.value` is true.

### Files

- `src/landing-page/style.css` — spring vars, upgraded easing, button states, stagger child CSS, caption fade, timeline dot pulse.
- `src/landing-page/index.html` — IntersectionObserver stagger logic for section children, demo caption fade class.
- `src/dashboard/src/styles.css` — TransitionGroup enter/leave classes, player expand transition, button `:active`, card `transition`, loading pulse.
- `src/dashboard/src/App.vue` — `<TransitionGroup>` wrapping cards, `--i` index on each card.
- `src/dashboard/src/components/ReadCard.vue` — `<Transition>` with JS hooks on the `.player` div.

### Out of scope

- Framer Motion, GSAP, or any animation library — CSS + Vue transitions only.
- Animating the search input, sort toggle, count label, or header.
- Waveform or transcript animations (already solid).
- The CLI / Python server.
- Mobile gesture animations (drag-to-delete etc.).

### Verification

1. **Landing page hero** — open `src/landing-page/index.html` locally; wordmark, tagline, pitch, and CTA each rise with a subtle spring overshoot, staggered ~120ms apart.
2. **Landing page scroll** — scroll down; feat-grid items, timeline entries, and stack-list rows each stagger in individually (not the whole section at once).
3. **Landing page buttons** — hover `.btn` lifts 1px; click → scales down and springs back.
4. **Dashboard card entrance** — load the dashboard; cards stagger in on initial load; "Load more" appends also stagger.
5. **Dashboard active card** — click play; player panel accordion-expands smoothly. Click another card → old panel collapses, new opens.
6. **Dashboard delete** — card slides left + fades out before disappearing (no layout jump).
7. **Dashboard play button** — visible press-down scale on click.
8. **Reduced motion** — DevTools → Rendering → "prefers-reduced-motion: reduce" → no animations on either surface.

---

## 2026-06-13 — Landing page → `src/landing-page/` + a landing-page skill

**Status: done** — on branch `feat/dashboard` (PR #12). Repo reorg + a new skill;
landing-page *content* refresh deferred.

### Context

`site/` lived at the repo root (the v2.0.0-era "marketing, not a client" call).
With `src/cli`, `src/dashboard`, etc. all grouped under `src/`, the landing page
belongs there too. Also: the page is stale vs v3.0.0 (all-CLI, no dashboard), and
there was no repeatable way to keep it current — so add a skill for that.

### What shipped

1. **Moved `site/` → `src/landing-page/`** (`git mv` index.html + style.css; the
   gitignored local `media/` preview copy moved alongside). Updated every
   reference in lockstep: `.gitignore` (`src/landing-page/media/`),
   `.github/workflows/pages.yml` (trigger `paths: src/landing-page/**`,
   `cp -R src/landing-page/.`, **+ `dashboard.png` added to the media copy list**),
   and the CLAUDE.md tree + `style.css` mentions.
2. **New `.claude/skills/landing-page/` skill** — "doc-sync for the marketing
   site": maps shipped changes → page sections, pulls screenshots from
   `docs/media/`, enforces the crossfade slide/dot/caption parity + the pages.yml
   media-copy rule, mandates a local serve+screenshot review, and notes the Pages
   auto-deploy on push to main.
3. **Kept GitHub Pages auto-deploy** — workflow repointed at the new path.

### Out of scope (deferred)

- **Landing-page content refresh** for v3.0.0 (dashboard section, `dashboard.png`
  screenshot, two-client "How it works", persistence in Features/Architecture) —
  done in a later pass via the new skill.

### Verification

1. Move clean: `git ls-files src/landing-page` shows index.html + style.css; root
   `site/` gone. ✓
2. Local render: `python3 -m http.server -d src/landing-page` → `/`, `style.css`,
   `media/*` all 200; headless screenshot renders correctly (no broken images /
   overflow). ✓
3. No stale `site/` references in current docs/workflow (PLAN history excepted). ✓
4. Pages: after merge to main, the workflow runs (path trigger fires) and the live
   site returns 200. *(verify post-merge)*

---

## 2026-06-13 — Library dashboard (persist reads + Vue web UI)

**Status: done** — branch `feat/dashboard`, PR #12. A SQLite library that records
every synthesized read, plus a Vue 3 web dashboard to search, sort, and replay
the audio anytime. Local env only; Pi deploy shipped separately (see 2026-06-15 entry).

Original concept sketch (the brief that kicked this off):

![Dashboard concept sketch](media/dashboard-plan.png)

**Shipped (2026-06-13):** `src/readback/library.py` (`Library` over stdlib
sqlite3 — per-call connections, `add/list/get/delete`); persist in
`_run_read_job` step 4b (best-effort, logged); `ReaderConfig.library_db`
(default `../readback-audio-db/library.db`, resolved in `load()`);
REST `GET /api/library?q=&sort=`, `GET /api/library/{id}`,
`DELETE /api/library/{id}`; built dashboard mounted at `/` when present.
`src/dashboard/` = Vue 3 + Vite + TS (App/SearchBar/SortToggle/ReadCard, one
shared `<audio>`, debounced search, delete-confirm), Ghost palette + IBM Plex
Mono / Martian Mono — `bun run build` clean (vue-tsc, ~27 KB gz).
**Verified:** seeded the real DB → list newest/oldest ordering, `q=` search over
title (`pelican`) + summary (`terminal`), `GET /{id}`, `GET /` serves the SPA
(200 text/html), `/audio/{wav}` 200, `DELETE` removed both row and WAV (404 on
unknown id/get); Full-mode excerpt vs Summary-mode summary both stored; seed
rows cleaned up after. Per-read persist + CLI path unchanged.
**Follow-ups (same day):** the active card grew into a **full player** —
click-to-seek bar, `elapsed / total`, ±5 s skips, pause/resume/replay, and
`space` + `←/→` keyboard parity with the CLI (ignored while the search box is
focused); a playing **Summary** read shows a **synced karaoke transcript**
(word-by-word accent-blue highlight, char-count-proportional timing lifted from
`cli/.../PlayerView.tsx`). Fixed a layout bug where Vue's whitespace-condensing
stripped the inter-word spaces in the transcript (words glued together +
overflowed the card) — render two segments + dynamic joiner space, plus
`overflow-wrap: anywhere` guards; verified via headless-Chrome CDP
(`scrollWidth == clientWidth`). Added `docs/media/dashboard.png` (real capture
of list + active player + blue transcript) to README + dashboard README; README
gained a "Why generation stays on the CLI" rationale (heavy LLM+TTS = on-demand
CLI work; replay = model-free dashboard path) mirrored into ARCHITECTURE §1/§5.
**Released v3.0.0** (major — the browser UI returns, reversing v2.0.0's removal,
and the on-disk audio/DB layout moved out of `~/.readback/`): bumped all four
anchors (pyproject / `__init__` / cli+dashboard `package.json`) +
CLAUDE/ARCHITECTURE version labels.
**Audio relocation (post-release):** moved `output_dir` out of the hidden
`~/.readback/reader/` into a sibling `readback-audio-db/audio/` folder next to
the repo (audio + DB together, harder to delete by accident). Config defaults now
use **`../` relative notation** (resolved against `config.yaml`'s dir, then
`.resolve()`d) so no personal absolute path leaks into the public repo; `load()`
resolves `output_dir` like `library_db`. The server reports the resolved dir as
`audio_dir` in `/api/config` + WS `config`, and the CLI's `resolveWav` uses it for
the same-machine playback shortcut (cache moved to `~/.readback/cli-cache/`).
Migrated the 5 tracked WAVs + rewrote their `audio_path`; deleted 23 orphan WAVs.
**Deferred:** Pi/remote deploy + Mac→Pi audio sync; backfill of pre-existing
orphan WAVs; WAV auto-rotation (manual delete only).

### Context

Today a read is ephemeral: `_run_read_job` writes `~/.readback/reader/<uuid>.wav`,
emits a `done` payload, and forgets it. The user wants to **replay any past read
on demand** from a browser dashboard (eventually served from a home Pi —
`github.com/MKS-01/pizow` — while the Mac stays the LLM+TTS brain). Two gaps:
(1) nothing persists read metadata, (2) there is no web client (the v2.0.0 pivot
removed the old browser read-UI on purpose — `GET /` returns 404). This feature
adds a **new, separate read-only library UI**, not a resurrection of that client.

Key constraint from the flow sketch: **audio files stay in the local Mac
directory only**; the DB stores their absolute path so the Pi host can sync and
serve them (shipped: `scripts/sync-pi.sh`). Must stay lightweight (Pi-friendly): a built SPA is static files,
so runtime cost is just FastAPI + SQLite (stdlib, near-zero RAM).

Decisions (confirmed with user): **Vue 3 + Vite + TS**; **delete capability
included** (also closes the "WAVs grow unbounded" roadmap item); DB lives at
**`../readback-audio-db/library.db`** (sibling to the repo).

### Design

1. **DB layer — `src/readback/library.py`** (new). Stdlib `sqlite3`, one table
   `reads`. No ORM. A thin `Library` class: `__init__(db_path)` creates the dir +
   table if missing (idempotent `CREATE TABLE IF NOT EXISTS`); methods
   `add(record)`, `list(q, sort)`, `get(id)`, `delete(id) -> audio_path|None`.
   Connections are opened per-call (`sqlite3.connect`) so it's safe across
   asyncio's threadpool — all DB calls go through `asyncio.to_thread`.

   Schema (`reads`):
   - `id` TEXT PRIMARY KEY — the WAV's uuid stem (matches "id: audio file name")
   - `title` TEXT
   - `summary` TEXT — spoken summary (Summary mode), NULL in Full mode
   - `excerpt` TEXT — first ~300 chars of article text (always present, so Full
     reads still show a 2-3 line preview in the card)
   - `source_url` TEXT — for "read the original"
   - `mode` TEXT — `full` | `summary`
   - `voice` TEXT — active voice id at synth time
   - `duration_sec` REAL
   - `word_count` INTEGER
   - `audio_filename` TEXT — `<uuid>.wav`
   - `audio_path` TEXT — absolute Mac path
   - `created_at` TEXT — ISO-8601 (date of extraction/creation)

2. **Persist on read — `server/server.py`**. In `_run_read_job` step 4, right
   after `write_wav` succeeds, call `library.add(...)` via `asyncio.to_thread`
   with the fields already in scope (`article.title`, `url`, `mode`, `voice`,
   `text`, `article.text[:300]`, durations, counts, `fname`, absolute path).
   Wrapped in try/except + log — a DB failure must never break playback. The
   `Library` is instantiated once in `create_app` and passed into
   `_run_read_job` (mirrors how `models`/`cfg` are threaded through).

3. **Config — `config.py`**. Add `ReaderConfig.library_db: Path =
   Path("../readback-audio-db/library.db")`, expanded at use. `load()`
   resolves it like the other paths. (Configurable, not hard-coded.)

4. **REST API — `server/server.py`** (read-only + delete; no WS changes):
   - `GET /api/library?q=<str>&sort=newest|oldest` → `[{...card fields...}]`.
     `q` filters title/summary/excerpt/source_url (SQL `LIKE`, case-insensitive);
     `sort` orders by `created_at` (default `newest`).
   - `GET /api/library/{id}` → full record (full summary text for the toggle).
   - `DELETE /api/library/{id}` → removes the row, then unlinks the WAV from
     `~/.readback/reader/`. Returns `{deleted: true}`.
   All wrap blocking sqlite in `asyncio.to_thread`.

5. **Serve the dashboard — `server/server.py`**. If `src/dashboard/dist` exists,
   mount it at `/` (`StaticFiles(..., html=True)`); otherwise keep the 404 (dev
   uses the Vite dev server on :5173 proxying `/api` + `/audio` → :8000). This is
   the one deliberate change to the "no browser UI" rule — scoped to a built
   artifact, additive to the WS/API backend.

6. **Frontend — `src/dashboard/`** (new; Vue 3 + Vite + TS, sibling to
   `src/cli`). Single-view SPA:
   - **Design system reused verbatim**: Ghost palette `:root` vars + the IBM Plex
     Mono / Martian Mono Google-Font links lifted from `site/style.css`. Dark
     terminal aesthetic, accent `#4da3ff`. Feels like the landing page.
   - **Layout**: header (wordmark + "library" subtitle) → a **search input** +
     **sort toggle** (Newest ↔ Oldest) → a vertical list of **read cards**.
   - **Card**: title (bright), meta line (date · duration · mode · voice ·
     word count), 2-3 line clamped summary/excerpt, a **"Show more" toggle**
     that expands the full summary, a **play button** (HTML5 `<audio>` pointing
     at `/audio/<filename>`, with seek), a **source-URL** link ("read original
     ↗"), and a **delete** affordance (confirm before firing DELETE).
   - **State**: `fetch('/api/library?q=&sort=')`, debounced search (~200 ms),
     client re-fetch on sort change. One global `<audio>` element so only one
     read plays at a time.
   - **Build**: `bun install && bun run build` → `dist/`; `bun run dev` for the
     proxying dev server. A short `src/dashboard/README.md` documents both.

### Files

- `src/readback/library.py` (new): `Library` class — sqlite schema + CRUD.
- `src/readback/config.py` (modified): `ReaderConfig.library_db` + path resolve.
- `src/readback/server/server.py` (modified): instantiate `Library`; persist in
  `_run_read_job` step 4; `GET /api/library`, `GET /api/library/{id}`,
  `DELETE /api/library/{id}`; mount `src/dashboard/dist` at `/` when present.
- `src/dashboard/` (new): Vue 3 + Vite + TS app — `package.json`,
  `vite.config.ts` (dev proxy), `index.html`, `src/main.ts`, `src/App.vue`,
  `src/components/{SearchBar,ReadCard,SortToggle}.vue`, `src/api.ts`,
  `src/styles.css` (Ghost palette), `README.md`.
- `docs/ARCHITECTURE.md`, `CLAUDE.md`, `README.md` (doc-sync at the end).

### Out of scope

- **Pi / remote deployment, nginx, audio sync Mac→Pi** — explicitly later.
- **Auth / multi-user** — local single-user only.
- **No WS protocol change** — the read flow is untouched; the dashboard is a
  pure REST+static client. The CLI is unaffected.
- **No backfill** of the ~24 existing orphan WAVs in `~/.readback/reader/` (no
  metadata to recover). Library starts populating from the next read. (Could add
  a one-off backfill script later if wanted.)
- **No WAV auto-rotation policy** — delete is manual via the dashboard.
- **No `config.yaml` write-back.**

### Verification

1. **DB bootstrap**: fresh run with no DB → first read creates
   `../readback-audio-db/library.db` + `reads` table; `sqlite3 …
   "SELECT id,title,mode FROM reads"` shows the row.
2. **Persist both modes**: a Full read stores `summary=NULL` + non-empty
   `excerpt`; a Summary read stores both. `audio_path` is the real absolute WAV
   path and the file exists there.
3. **List + search**: `GET /api/library` returns newest-first; `?sort=oldest`
   flips it; `?q=<word from a title>` filters to matching rows only.
4. **Dashboard happy path**: `bun run dev` → cards render in Ghost styling with
   correct fonts; search box filters live; sort toggle reorders; "Show more"
   expands the full summary; play button streams the audio and seeks; source
   link opens the original.
5. **Delete**: delete a card → confirm → row gone from `GET /api/library` AND
   the WAV removed from `~/.readback/reader/`; refresh shows it stays gone.
6. **Resilience**: stop/point DB at an unwritable path → a read still synthesizes
   and plays (CLI unaffected); the persist failure is logged, not fatal.
7. **Built mount**: `bun run build` → restart `readback` → `GET /` serves the
   dashboard; CLI (`/ws`) still works unchanged.
8. **Restart persistence**: kill + restart the server → past reads still listed.

---

## 2026-06-13 — Landing page on GitHub Pages

**Status: done** — branch `landing-page`, PR #11 merged 2026-06-13. Static
one-page site + the repo's first GitHub Action; zero changes to `src/`.
Shipped: `site/index.html` + `style.css` (Ghost-palette terminal page with an
inline sample-read player), `.github/workflows/pages.yml` (copies media from
`docs/media/` into the artifact), Pages enabled with the Actions source.
Verified: workflow run green, `https://mks-01.github.io/readback/` live —
page + css + all media return 200, headless-Chrome render matches local, no
viewport overflow.
Follow-ups (same day): ASCII flow chart rebuilt as HTML/CSS boxes (box-drawing
glyphs aren't in the IBM Plex Mono webfont — fallback glyph widths shattered
it); motion pass (scroll-reveal sections, animated flow connectors, breathing
feature markers, `prefers-reduced-motion` respected); a brief `site/blog/`
(3 notes pages) was added then removed the same day — direction settled on a
strict one-pager with "The story" (the voice-assistant pivot) folded in;
"Stack" then reworked into a six-concept "Architecture" section (gemma kept
as the example, "any chat model works — we ran gemma & qwen"); all 3 CLI
screenshots in a slow auto-crossfade (6 s, clickable dots, holds on hover);
sample player upgraded to a 52-bar waveform (picked from 4 rendered variants —
click-to-seek, played bars sway while audio runs); blinking block caret
swapped for an underscore cursor (it read as a broken glyph next to the `$`);
footer trimmed to GitHub + MIT. Workflow copies all of `site/` + 4 media
files into the artifact. Repo About now points at the Pages URL and carries
16 topics (tts/mlx/apple-silicon/ollama/…).

### Context

readback is open source but has no web presence beyond the GitHub README. A
minimalist landing page gives the project a linkable home — and since the
product *makes audio*, the page can do what the README can't: play the sample
read inline. Constraint: the v2.0.0 pivot deliberately removed the web
frontend, so the site must live outside `src/` as pure static marketing, not a
client. Hosting: GitHub Pages (free), deployed by GitHub Actions per the
user's ask.

### Design

1. **`site/` at the repo root** — standalone static site: `index.html` +
   `style.css`, hand-written, no framework, no build step. Never imports or
   serves anything from `src/`.
2. **Look: the product's own aesthetic.** Dark terminal page using the CLI's
   Ghost palette — `#f0f0f0` primary / `#808080` dim / `#4da3ff` accent
   (`theme.ts` is the source of truth) — monospace type, the wordmark PNG as
   the hero. The page should read like the CLI screenshots beside it.
3. **Sections** (single scroll, in order): hero (wordmark, tagline "Make
   reading interesting again", one-line pitch, `git clone` CTA + GitHub
   button) → inline **audio player** with `sample-read.wav` → screenshot
   (`cli-player.png`) → features grid (100% offline / CSM-1B voice + cloning /
   Summary mode via local LLM / real terminal player with seek + synced
   transcript) → how-it-works pipeline (the README's ASCII diagram in a
   `<pre>`) → quick start (the README's 4-step code block) → open-source
   footer (MIT, GitHub, issues, "Built on Apple Silicon · MLX").
4. **Media is not duplicated in git.** `site/` holds only html/css; the deploy
   workflow copies `docs/media/{wordmark.png, cli-player.png, cli-home.png,
   sample-read.wav}` into the artifact's `media/` before upload. The page
   references `media/…` relatively.
5. **Workflow `.github/workflows/pages.yml`** — on push to `main` (paths:
   `site/**`, `docs/media/**`, the workflow itself) + `workflow_dispatch`:
   checkout → assemble `_site` (site/ + media copy) →
   `actions/upload-pages-artifact` → `actions/deploy-pages`. Standard
   `pages: write` / `id-token: write` permissions, `github-pages` environment.
6. **Pages source = GitHub Actions** — one-time repo setting via
   `gh api repos/MKS-01/readback/pages -X POST -f build_type=workflow`.
   Site URL: `https://mks-01.github.io/readback/`.

### Files

- `site/index.html` (new): the one-page site.
- `site/style.css` (new): Ghost-palette styling.
- `.github/workflows/pages.yml` (new): assemble + deploy to Pages.
- `docs/PLAN.md` (modified): this entry.
- `README.md` (modified): link the live site under the badge row.

### Out of scope

- No JS framework, no build tooling, no analytics, no custom domain.
- No docs site / multi-page — README and `docs/` stay the documentation home.
- No re-introduction of any web client; the page is static marketing only.
- No CI beyond the Pages deploy (tests/lint workflows are a separate decision).

### Verification

1. `open site/index.html` locally (with media copied in) — renders correctly,
   audio plays, links resolve.
2. Merge to `main` → the `pages.yml` run goes green end-to-end.
3. `https://mks-01.github.io/readback/` loads: wordmark crisp, sample WAV
   plays inline, screenshots load, GitHub links work.
4. Lighthouse-level sanity: page is responsive at phone width; no console
   errors; total weight dominated only by the media files.

## 2026-06-12 — Folder restructure: src/ layout + docs/

**Status: done** — branch `depreciate/web` (continues PR #10, same post-web
cleanup umbrella). Top-level reorganization only; zero code-logic changes.
Shipped: everything python-side under `src/` (`readback/`, `cli/`, `voice/`,
`finetune/`), all docs caps-named under `docs/` (`ARCHITECTURE.md`, `SETUP.md`,
`PLAN.md` + `media/`). Riding along: `docs/SETUP.md` and `docs/ARCHITECTURE.md`
rewritten for the CLI-only era (both still described the deleted web
frontend/TLS). Verified: editable install + imports, server 200/404, CLI
dev-mode auto-spawn from the new depth, `install.sh` binary bakes the correct
repo root, stale-path sweep clean.

### Context

After the web deletion and package rename, the repo root holds 7 markdown/config
files plus 6 directories — the Python package sits at top level next to the CLI,
and docs are scattered. Goal: a conventional layout where the Python backend
lives under `src/` (standard src-layout), the CLI stays a clear sibling at
`cli/`, and reference docs collect under `docs/` — leaving the root with just
the entry-point files (`README.md`, `CLAUDE.md`, `config.yaml`,
`pyproject.toml`, `plan.md`, `LICENSE`).

Research confirmed the moves are cheap: the package has no `__file__` path
tricks, `config.yaml` resolves from cwd (the CLI spawns the server with
cwd = repo root), and only two spots derive the repo root relative to `cli/`
(`install.sh`, `server.ts`) — each needs one extra `..` when `cli/` moves
under `src/`.

### Design

1. **`src/` layout — both clients**: `git mv readback/ src/readback/` and
   `git mv cli/ src/cli/`. Update `pyproject.toml`:
   `packages = ["src/readback"]`. No Python import changes — the package name
   is unchanged. Requires one `pip install -e .` re-run.
2. **Root-derivation fixes** (the only code-path edits):
   - `src/cli/install.sh`: `REPO_ROOT="$(cd .. && pwd)"` → `cd ../..`.
   - `src/cli/src/server.ts`: dev fallback `resolve(import.meta.dir, "..", "..")`
     → `"..", "..", ".."`.
3. **`docs/`** — all caps-named: `docs/ARCHITECTURE.md`, `docs/SETUP.md`,
   `docs/PLAN.md` (renamed from `plan.md`), `docs/media/`. Fix links in
   `README.md` (SETUP, ARCHITECTURE, 4 media images + sample WAV),
   `src/cli/README.md` (media images, `../media/` → `../../docs/media/`), and
   `CLAUDE.md` (ARCHITECTURE link + project-structure map).
4. **`voice/` → `src/voice/`, `finetune/` → `src/finetune/`** — python-side
   assets grouped under `src/` (as siblings of the package, NOT inside
   `src/readback/`, so they don't ship in the wheel). Path updates:
   `config.yaml` (`wav:` + `lora_path` comment), `.gitignore` (wav exceptions +
   finetune ignores), `src/finetune/README.md` self-referencing commands,
   `csm-voice` skill paths.
5. **Stays at root**: `README.md` (GitHub landing + pyproject `readme`),
   `CLAUDE.md` (user request), `config.yaml` (cwd-resolved at runtime),
   `LICENSE`.
5. **Stale-doc fixes riding along**: `SETUP.md` drops the Node.js/React
   frontend prerequisite + build step (web is gone); the `doc-sync` skill's
   `readback/web/server.py` reference becomes `src/readback/server/server.py`;
   `cd cli` install instructions become `cd src/cli` everywhere.
6. **CLAUDE.md project-structure block** rewritten to the new tree.

### Files

- `readback/` → `src/readback/` (git mv, no content changes).
- `cli/` → `src/cli/` (git mv).
- `src/cli/install.sh` (modified): repo-root derivation one level deeper.
- `src/cli/src/server.ts` (modified): dev repo-root fallback one level deeper.
- `ARCHITECTURE.md` → `docs/ARCHITECTURE.md`; `SETUP.md` → `docs/SETUP.md`
  (+ stale frontend refs removed); `plan.md` → `docs/PLAN.md`;
  `media/` → `docs/media/`.
- `voice/` → `src/voice/`; `finetune/` → `src/finetune/` (+ path updates in
  `config.yaml`, `.gitignore`, `src/finetune/README.md`, `csm-voice` skill).
- `pyproject.toml` (modified): wheel packages path.
- `README.md` (modified): doc + media links, `cd src/cli`.
- `src/cli/README.md` (modified): media links.
- `CLAUDE.md` (modified): structure map, ARCHITECTURE link, install notes.
- `.claude/skills/doc-sync/SKILL.md` (modified): doc paths.

### Out of scope

- Moving `config.yaml` (stays at root, cwd-resolved).
- Any logic changes — only the two root-derivation constants change in code.
- Rewriting SETUP.md beyond deleting the dead frontend steps.

### Verification

1. `pip install -e .` succeeds with the src layout; `readback` entry point works.
2. `python -c "from readback.server.server import create_app; print('ok')"`.
3. `readback` boots; `GET /api/config` → 200; `GET /` → 404.
4. `cd src/cli && bun run start` — auto-spawn + full read flow works
   (cwd-relative `config.yaml` still resolves from the derived repo root).
5. `cd src/cli && ./install.sh` — compiled binary bakes the right repo root,
   finds the venv server.
6. All README/cli README image + doc links resolve; no stale `cd cli` /
   `media/` / root `ARCHITECTURE.md` references remain.

---

## 2026-06-12 — Restructure Python package: pipeline/ + server/

**Status: done** — branch `depreciate/web` (runs after web deletion is done).
Rename `reader/` → `pipeline/` and `web/` → `server/` for accurate, durable naming.
Zero behavior change; import fixes only.

> **Why now:** With the browser UI gone, `web/` is a misnomer (it's a WS/REST server,
> not a web app) and `reader/` was always the old feature label, not a description
> of what the code does. Clean names before the project settles as CLI-only.

### Context

Two folder names became stale after the v0.8.0 pivot and the web deletion:
`reader/` was named after the "article reader" feature, not its role (processing
pipeline: extract → summarize → synthesize). `web/` implied a browser-facing layer
that no longer exists. Renaming both while the diff is small is lower risk than
accumulating a larger rename later. `llm/` and `tts/` are already well-named.

### Design

1. Rename `readback/reader/` → `readback/pipeline/`. Update the `__init__.py`
   self-references and `summarize.py`'s import of `extract`.
2. Rename `readback/web/` → `readback/server/`. `server.py` moves with it;
   update its three `readback.reader.*` import lines to `readback.pipeline.*`.
3. Update `__main__.py`: `readback.web.server` → `readback.server.server`.
4. Update `CLAUDE.md` module map and any `reader/` path references.

### Files

- `readback/reader/` → `readback/pipeline/` (renamed directory, 3 files + `__init__.py`).
- `readback/web/` → `readback/server/` (renamed directory, `server.py` + `__init__.py`).
- `readback/__main__.py` (modified): one import line.
- `readback/pipeline/__init__.py` (modified): self-import path.
- `readback/pipeline/summarize.py` (modified): one import line.
- `readback/server/server.py` (modified): three import lines (`readback.reader.*` → `readback.pipeline.*`).
- `CLAUDE.md` (modified): module map paths.

### Out of scope

- Any logic changes in any file.
- Renaming `llm/` or `tts/` — both names are accurate.
- CLI changes — the CLI has no Python imports.

### Verification

1. `python -c "from readback.pipeline import fetch_article; print('ok')"` — no ImportError.
2. `python -c "from readback.server.server import create_app; print('ok')"` — no ImportError.
3. `readback` starts cleanly; `GET /api/config` responds.
4. `bun run start` in `cli/` — full read flow works end-to-end.
5. No `readback.reader` or `readback.web` references remain (`grep -r "readback\.reader\|readback\.web" readback/`).

---

## 2026-06-12 — Delete web frontend; CLI-only project

**Status: done** — branch `depreciate/web`.
Remove the React/Vite browser UI and all its scaffolding; slim the server to a
pure CLI-backend (WS + `/audio` + `/api/*`). No protocol changes, no CLI changes.

> **Why we're discontinuing the web UI:** The browser client was the original
> interface, but the terminal CLI (v1.0.0) has fully replaced it as the daily
> driver. The React/Vite/three.js/zustand stack now only adds maintenance debt —
> a mandatory `npm run build` before every server start, TLS/cert machinery for
> LAN browser access, and a large `node_modules` tree to keep up to date. No new
> web features are planned and the CLI covers the full pipeline. Removing the
> frontend simplifies install to a single `pip install -e .` and eliminates the
> web maintenance surface entirely.

### Context

The browser UI (React 18 + Vite + three.js + zustand) was the original primary
client. The terminal CLI (v1.0.0) has since become the sole focus. The frontend
brings: npm/node_modules maintenance, a mandatory build step before server start,
TLS/cert machinery for LAN browser access, and the entire `web/frontend/` tree.
None of that serves the CLI. Deleting it simplifies install and removes the web
maintenance surface entirely.

The CLI still needs the Python server (FastAPI WS) — that is NOT removed.

### Design

1. Delete `readback/web/frontend/` and `readback/web/static/` entirely.
2. In `server.py`: remove `GET /` (index.html), `GET /cert.pem`, the
   `_no_cache_static` middleware, and the `StaticFiles` frontend mount.
   Keep `/ws`, `GET /api/config`, `GET /api/models`, and `/audio` (WAV serving).
3. In `__main__.py`: remove `--auto-cert`, `--cert`, `--key` flags and all TLS/cert
   generation logic (`_ensure_cert`, `_fingerprint`, cert banner output).
   Keep `--host`, `--port`, `--model`, `--config`.
4. In `pyproject.toml`: remove `cryptography` dep.
5. In README + CLAUDE.md: remove frontend build step from install instructions;
   update description to CLI-only.

### Files

- `readback/web/frontend/` (deleted): entire React/Vite app.
- `readback/web/static/` (deleted): Vite build output.
- `readback/web/server.py` (modified): remove HTML-serving routes + middleware.
- `readback/__main__.py` (modified): remove TLS/cert logic and flags.
- `pyproject.toml` (modified): remove `cryptography` dep.
- `README.md` (modified): remove `npm run build` step, update intro.
- `CLAUDE.md` (modified): remove frontend build from install section.

### Out of scope

- Any CLI changes (zero protocol impact).
- Removing `fastapi`, `uvicorn`, `python-multipart` — the WS server stays.
- Removing the `/audio` static mount — CLI player downloads WAVs from it.
- Any new CLI features.

### Verification

1. `pip install -e .` succeeds (no `cryptography` dep error).
2. `readback` starts without `--auto-cert` and prints local URL with no cert/fingerprint output.
3. `readback --auto-cert` prints an unknown-flag error (flag is gone).
4. `GET http://127.0.0.1:8000/` returns 404 (no index.html served).
5. `bun run start` in `cli/` — spawns server, paste a URL, audio plays. Full flow works.
6. `/model`, `/voice`, `/mode` all function normally in the CLI.

---

## 2026-06-12 — CLI model switch (`/model`) — list local Ollama models + RAM-fit suggestion

**Status: done** — shipped on branch `feat/model-switch` (2026-06-12), version
bumped to **v1.1.0**: `readback/llm/models.py`, `/api/models`, per-read
`model` swap, CLI `/model` command + prefs. Post-review additions: colored fit
verdicts (`ModelList.tsx`; green fits / yellow tight / red too-big, new
GREEN/YELLOW theme colors) and `/model` added to the home-screen hint line.
Verified end-to-end by driving the TUI through a pty (expect): list +
recommendation, switch + StatusLine + prefs persistence across restart,
unknown-name error, per-read swap confirmed server-side (`/api/config` flipped
mid-session). CLI scope only; web UI gets its own plan later.

### Context

Summary mode uses one Ollama model, fixed in `config.yaml` (`gemma4:26b`) at
server boot. Goal: switch the summary LLM from the terminal CLI without a
restart — a `/model` command that **lists all locally downloaded Ollama
models**, **flags which fit this Mac's RAM** (avoid swap/thrash later), and
**suggests the ideal one for summarization**, then switches to it. Mirrors the
existing `/voice` flow end-to-end.

A small server change is unavoidable (the LLM lives in the Python server), but
it's tiny: `LLMClient.oneshot()` reads `self.cfg.model` fresh on every call
(`llm/client.py`), so swapping = mutating `cfg.ollama.model` — no reload. The
bundled `ollama` lib already has `Client.list()` (`/api/tags`) for discovery.

### Design

1. **`GET /api/models`** (new, `web/server.py`, next to `/api/config`) — logic
   in a new **`readback/llm/models.py`** (reusable by the web client later):
   - `ollama.Client(host).list()` → per model: name, `size` bytes,
     `details.parameter_size`, `details.quantization_level`.
   - Total RAM via `sysctl -n hw.memsize` (fallback `os.sysconf`).
   - **Fit heuristic**: need ≈ `size × 1.2 + 1 GiB` (weights + KV/overhead);
     `good` if ≤ 50 % of total RAM, `tight` if ≤ 75 %, else `no` (reserve
     headroom for CSM + system).
   - **Recommendation**: largest `good` non-embedding model (skip names with
     `embed`/`bge`/`minilm`). Ollama down → `{"error": …, "models": []}`.
   - Shape: `{models: [{name, size_gb, params, quant, fit}], recommended,
     current, total_ram_gb}`.
2. **Per-read `model` field** on the `read` WS message — same semantics as
   `voice` (`_run_read_job`, applied *before* the summarize step): if set and
   different, validate against the installed list, then
   `cfg.ollama.model = model`; unknown name → `log.warning`, keep current.
   Global mutation like `swap_voice`; **no `config.yaml` write-back** (restart
   returns to the yaml default). Update the WS protocol docstring.
3. **CLI `/model`** (same UX as `/voice`):
   - `/model` → fetch `/api/models`, render in the notice pane: ★ current,
     → recommended, per row `size GB · params · fit` text; hint
     `/model <name> to switch · used by Summary mode only`. Cache the list in
     a ref for arg validation.
   - `/model <name>` → validate against the list, `setModel`, persist, notice.

### Files

- `readback/llm/models.py` (new): `list_models`, `installed_model_names`.
- `readback/web/server.py`: `/api/models` route; model swap in `_run_read_job`;
  protocol docstring.
- `cli/src/ws.ts`: `read(url, mode, voice, model)`.
- `cli/src/prefs.ts`: `model: string | null`.
- `cli/src/app.tsx`: `model` state (init `prefs.model ?? cfg.model`) +
  `setModel` action; `/model` command; pass `state.model` to `StatusLine` and
  `read()`; persist; HELP text.
- `cli/src/components/StatusLine.tsx`: no change (prop already exists).

### Out of scope

Web frontend UI; `config.yaml` write-back; `ollama pull` (installed-only).

### Verification

1. `cd cli && bun run start` → `/model` lists installed models with sizes, fit
   tags, ★ on `gemma4:26b`, → on the recommendation.
2. `/model <other-model>` → notice + StatusLine update; persisted in
   `~/.readback/cli.json`; survives a CLI restart.
3. Summary-mode read → server log `summary model → …`; `ollama ps` shows the
   chosen model during the summarizing phase.
4. `/model not-a-model` → error banner; current model unchanged.
5. Ollama stopped → `/model` shows a clean error banner, no crash.
6. `curl http://127.0.0.1:8000/api/models | jq` matches the documented shape.

---

## 2026-06-11 — CLI mode — Bun + Ink terminal client

**Status: in progress** — implemented on branch `cli-mode`; docs + version bump
(0.9.0) landed; manual verification underway.

**2026-06-12 additions** (same branch, post-review with user): half-block
wordmark banner (`Header.tsx`, READ white / BACK Xcode-blue `#4da3ff`, chosen
over icon-art variants); blue accents (caret, version, progress fills,
slash-command hints); **seek ←/→ ±5 s** via WAV PCM slicing to a temp file
(afplay can't seek); **word-synced transcript highlight** (char-proportional
timing estimate; self-wrapped lines because ink `wrap="wrap"` breaks colored
spans); resize repaint via `prependListener` clear (alt-screen tried, glitchy
in Warp, reverted); `install.sh` one-command standalone binary →
`~/.local/bin/readback-cli` (repo root baked via `--define`). Docs updated
(cli/README, root README CLI section, CLAUDE.md) with screenshot placeholders
at `media/cli-{home,busy,player}.png` — paths pending from user.

### Context

A terminal client for readers who live in the shell — a **second client of the
existing FastAPI `/ws` protocol, zero Python changes**. Ink UI (React for
CLIs), themed to the web app's Ghost palette (#f0f0f0 primary, #808080 dim,
#ff5d5d errors/cancel only). Runtime: **Bun + TypeScript**.

### Decisions

- **Auto-spawn the server.** On start, health-check `GET /api/config`; if down,
  spawn `readback` (prefers `.venv/bin/readback`, cwd = repo root so
  `config.yaml` resolves), wait ≤60 s; on exit kill it only if we spawned it —
  SIGTERM then SIGKILL after 1.5 s (uvicorn's graceful shutdown can hang on the
  open websocket). `--no-spawn` opts out; `--host`/`--port` target a remote.
- **`afplay` player** (macOS-only): SIGSTOP/SIGCONT pause/resume (always
  SIGCONT before SIGTERM), no seeking, wall-clock elapsed; keys: space, t
  (transcript, Summary mode), q/esc. Local WAV from `~/.readback/reader/` when
  present, else download from `/audio`.
- **Interactive-only session**: bordered URL input + slash commands (`/voice`,
  `/mode`, `/help`, `/quit`); prefs persist to `~/.readback/cli.json`; esc
  cancels a running read. No one-shot/batch flags.
- **Ink screen model**: `useReducer` switches one mounted screen
  (input | busy | player) so keys only land on the active screen; `ws.ts` /
  `player.ts` are module singletons outside the React tree (web frontend
  pattern).

### Files

`cli/`: `package.json` (readback-cli 0.9.0), `tsconfig.json`, `README.md`,
`src/{index.tsx, app.tsx, theme.ts, server.ts, ws.ts, player.ts, prefs.ts,
components/{UrlInput,StatusLine,BusyView,PlayerView}.tsx}`. Docs: README /
CLAUDE / ARCHITECTURE / cli/README; version → 0.9.0 in the three Python-side
anchors + cli/package.json.

### Verification

`bun run start` with no server → auto-spawn + read + afplay playback; q exits
and the spawned server dies. With a server already running → connects, doesn't
kill it on exit. Cancel mid-synthesis (esc), Summary transcript toggle, prefs
survive a restart, `--no-spawn` fails fast when no server. Known caveats:
CLI SIGKILL orphans a spawned server; pause flushes ~0.5 s of buffer.

---

## 2026-06-10 — Tune CSM-1B by config (simple path; no model swap)

**Status: done (Step 1; Steps 2–3 deferred)** — applied 2026-06-10:
`precision: fp32`; kay ref upgraded to an 11 s CSM-bootstrapped clip
(`voice/voice_kay_long.wav`, transcript whisper-verified); summary LLM switched
to `gemma4:26b` (cleaner, structured spoken summaries; nemotron-3-nano was the
fallback). End-to-end sample verified: steady pacing, no instability; only
residual nit is occasional proper-noun articulation ("Fable" ≈ "Table"), which
is LoRA territory. **Step 2 (LoRA) deferred** — revisit only if articulation
bothers in real use; anything more now is overengineering.

### Context

Stay on CSM-1B (user decision — an engine swap was judged too expensive, and
earlier engine experiments had already been abandoned). csm-mlx runs the
**same weights** as the official release, and every lever that matters is
**already plumbed into `config.yaml`** — so the plan is staged: config-only
first, LoRA fine-tune only if that's not enough. **No app-code changes
anywhere.**

Why this works: the open 1B is a *base* model; the polished demo voices are
fine-tuned variants conditioned on good reference audio. Better reference +
right precision/temperature is the first half of that recipe; the LoRA is the
second.

### Step 1 — Config-only tuning (~1 hour, no code)

1. **Better reference clip — the biggest lever.** Current kay ref is one short
   ~4–5 s clip; a clean **8–10 s** clip conditions far more reliably (per
   `.claude/skills/csm-voice`). More kay-source audio if available, else any
   clean recording of a voice you like:
   `scripts/make_clone_voice.sh <in> voice/kay2.wav` → exact transcript via
   one-off mlx-whisper (install → transcribe → uninstall, the skill's pattern)
   → update `wav:` + `ref_text:` under `tts.csm.voices`.
2. **`precision: "fp32"`** — max quality; RTF ~1.4 is fine for an offline reader.
3. **Temperature**: render the same paragraph at 0.6 and 0.7, keep the one that
   sounds better (0.6 measured, 0.7 livelier). Two runs, not a grid.
4. Restart the server, read one real article end-to-end, judge by ear.

### Step 2 — LoRA fine-tune (only if Step 1 isn't enough; the real jump)

Follow `finetune/README.md` **verbatim** — commands already M5/48 GB-tuned:
1. Data: one **LibriVox narrator** (clean public-domain read-speech), 30–60 min
   of chapters → split to 5–15 s clips (ffmpeg) → `finetune/data/` layout.
2. `finetune/transcribe.py` (one-off mlx-whisper) → review transcripts.
3. `csm-mlx finetune convert finetune/data finetune/dataset.json`
4. `csm-mlx finetune lora sft --data-path finetune/dataset.json
   --output-dir finetune/runs/v1 --lora-rank 8 --lora-alpha 16 --epochs 10
   --batch-size 1 --gradient-accumulation-steps 8 --gradient-ckpt
   --learning-rate 5e-4`
5. Result is again just config: `lora_path: "finetune/runs/v1"` +
   `temperature: 0.8`. Quick-check synth (README one-liner), then the server.

### Step 3 — Optional, later (on request only)

YouTube voice extraction for a specific person's voice (yt-dlp + diarization +
review pass). Skipped for now — LibriVox covers the quality goal without the
extra deps and script.

### Deliberately cut for simplicity

Multi-clip conditioning (code change), WER bench script, chunk-size and sampler
experiments, mlx upgrade. Revisit only if Step 2 still disappoints.

### Files touched

- Step 1: `config.yaml`, `voice/*.wav` — nothing else.
- Step 2: `finetune/data/*` + `finetune/runs/v1` + two `config.yaml` lines.

### Verification

- Same test paragraph synthesized before/after each change; pick by ear.
  (Optional: one one-off mlx-whisper transcription to count word errors.)
- Server smoke after each config edit (restart required): paste an article URL
  → Full mode → play + download work; cancel still works (no code touched).

### Honest expectations

Step 1 tightens voice consistency and clarity; Step 2 (LoRA on fluent
narration) is what removes the conversational/halting character and gives the
composed "narrator" delivery — the same move Sesame made for its demo voices. A
tuned 1B won't fully equal their hosted demo (a larger fine-tuned variant), but
it's the best this hardware does without the 8B-class cost already ruled out.

---

## 2026-06-10 — TTS engine upgrade + accuracy bench (researched, dropped)

**Status: superseded (same day)** — explored swapping the TTS engine for a
larger model behind a new adapter, with a WER/RTF bench to pick the default.
Direction changed the same day to staying on CSM-1B and tuning it (see the
entry above): an engine swap was judged too expensive for the gain, and the
sample analysis showed the remaining gap was model-level naturalness — pacing
was already fixed by `_tidy_silence` (zero pauses ≥ 0.35 s in the outputs).
The detailed research notes (candidate models, bench harness design, adapter
sketch) were removed from this file once the decision landed.
