"""Reader: fetch a URL → extract the article → (optionally summarize) → speak.

The project pivoted from a real-time voice assistant to an offline article
reader in v0.8.0. Offline synthesis removes the real-time constraint that caused
the audio-underrun problems — we synthesize the whole piece, then play/download.
"""
from readback.pipeline.extract import Article, ExtractError, fetch_article

# ⚠ BUMP THIS whenever a change alters the AUDIO a given source produces — a new
# summary prompt, a change to chunking/pausing, or a synthesis fix. It is part of
# the read cache key, so bumping it makes previously-read URLs re-render instead
# of replaying a stale WAV. Without it the cache (keyed only on url/mode/voice/
# llm_model) silently serves audio made by the OLD pipeline, which is exactly the
# trap when you are A/B-ing a quality fix: you "re-read" the article and hear the
# very output you just fixed. Old rows have recipe '' and simply never match.
#
#   r2 — 2026-08-22: batched-synthesis padding mask (muffled voice), text-shaped
#        inter-chunk pauses, paragraphed summaries.
RECIPE_VERSION = "r2"

__all__ = ["Article", "ExtractError", "RECIPE_VERSION", "fetch_article"]
