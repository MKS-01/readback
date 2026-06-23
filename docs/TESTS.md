# Test Coverage

38 tests across 8 files. Pure logic only — no MLX, no CSM, no GPU. Runs on
Linux (CI) and macOS (local). Config in `pyproject.toml`
(`[tool.pytest.ini_options]`).

```
pytest                        # run all
pytest tests/test_library.py  # run one file
pytest -k "cache"             # run by keyword
```

---

## Pipeline — `speak.py`

### Chunking (`test_chunk_text.py` — 4 tests)

| Test | What it guards |
|------|----------------|
| `short_text_is_a_single_chunk` | Empty/short input produces 0/1 chunks |
| `sentences_merge_up_to_max` | Sentences pack into ≤ `_MAX_CHARS` chunks |
| `paragraph_boundary_forces_a_split` | `\n` between paragraphs = new chunk |
| `overlong_sentence_splits_on_commas` | Sentences > `_MAX_CHARS` split on `,` |

### Synthesis (`test_speak.py` — 3 tests)

| Test | What it guards |
|------|----------------|
| `fade_out_tail_ramps_to_zero` | 100 ms linear fade-out reaches zero, prefix untouched |
| `degenerate_chunk_retried` | All-silence chunk retries once and recovers |
| `degenerate_chunk_dropped_after_two_failures` | Two consecutive silences → chunk dropped cleanly |

### Silence tidying (`test_tidy_silence.py` — 4 tests)

| Test | What it guards |
|------|----------------|
| `all_silence_is_dropped` | Pure silence → empty array (chunk dropped) |
| `leading_and_trailing_silence_trimmed` | Voiced region extracted with pad |
| `internal_pause_capped` | Mid-utterance silence capped to `max_pause_ms` |
| `pure_voiced_is_left_intact` | No silence → audio unchanged |

---

## Pipeline — `extract.py`

### TTS scrubbing (`test_extract_clean.py` — 4 tests)

| Test | What it guards |
|------|----------------|
| `strips_urls` | `https://…` removed from article text |
| `strips_citation_markers_and_collapses_whitespace` | `[1]` markers gone, blank lines collapsed |
| `fallback_title_from_url_tail` | URL path → readable slug title |
| `article_word_count` | `Article.word_count` property |

---

## Pipeline — `summarize.py`

### Map-reduce batching (`test_summarize_batches.py` — 4 tests)

| Test | What it guards |
|------|----------------|
| `short_text_is_one_batch` | Empty/short input → 0/1 batches |
| `batches_respect_max_chars` | Every batch ≤ `max_chars`, no text lost |
| `oversize_paragraph_falls_back_to_sentences` | Paragraph > cap splits on sentence boundaries |
| `giant_single_sentence_is_hard_cut` | No sentence boundary → hard character cut |

---

## LLM — `client.py`

### Think stripper (`test_think_stripper.py` — 4 tests)

| Test | What it guards |
|------|----------------|
| `removes_a_think_span` | `<think>…</think>` stripped from output |
| `text_without_think_is_unchanged` | Clean text passes through |
| `unclosed_think_is_discarded_on_flush` | Unterminated `<think>` dropped on flush |
| `streaming_split_across_feeds` | Tag split across chunk boundaries still stripped |

---

## Pipeline — `tones.py` + `extract.py`

### Source classification & tones (`test_tones.py` — 5 tests)

| Test | What it guards |
|------|----------------|
| `url_classifies_as_article` | URL → `"article"` |
| `image_path_classifies_as_book` | Image path → `"book"` |
| `glob_classifies_as_book` | Glob pattern → `"book"` |
| `tone_for_maps_kind_to_tone` | `"book"` → BOOK, `"article"` → ARTICLE, unknown → ARTICLE |
| `book_tone_is_measured_article_is_livelier` | BOOK temperature < ARTICLE temperature |

---

## Library — `library.py`

### CRUD + cache (`test_library.py` — 10 tests)

| Test | What it guards |
|------|----------------|
| `add_then_get_roundtrip` | Insert → retrieve by id |
| `list_sort_newest_and_oldest` | Sort order (created_at DESC / ASC) |
| `search_matches_title_and_url` | `LIKE %q%` across title + source_url |
| `insert_or_replace_overwrites_same_id` | Re-insert same id updates, count stays 1 |
| `delete_returns_audio_path_and_removes_row` | Delete returns path, row gone, second delete → None |
| `find_cached_returns_latest_match` | Cache hit returns newest matching read |
| `find_cached_miss_on_different_voice` | Different voice → no cache hit |
| `find_cached_miss_on_different_model` | Different `llm_model` → no cache hit |
| `find_cached_miss_when_wav_deleted` | WAV file missing → no cache hit |
| `llm_model_persisted` | `llm_model` column round-trips through add/get |

---

## CI

GitHub Actions (`.github/workflows/ci.yml`): Python **3.10 + 3.12** on
Ubuntu. Installs `requirements-pi.txt` + pytest (no MLX/CSM — Linux-safe).
Test summary published as a PR check annotation via `pytest --junitxml`.

## Not tested (by design)

These require Apple Silicon + GPU and are verified by manual smoke test:

- CSM-1B synthesis (`tts/csm_engine.py`, `tts/synthesizer.py`)
- MLX LLM inference (`llm/client.py` `oneshot`)
- MLX vision OCR (`pipeline/extract.py` `_ocr_via_mlx`)
- Server WebSocket protocol (`server/server.py` `/ws`)
- CLI playback + UI (`src/cli/`)
