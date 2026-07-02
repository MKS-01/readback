"""Summary / explainer mode: turn an extracted article into a spoken-friendly
explanation via the LLM. (Verbatim mode skips this and reads the text directly.)

Short articles are a single `oneshot`. Long inputs (whole book scans via
multi-page OCR) exceed the model's context, so they're **map-reduced**: split into
batches, condense each (map), then combine the digests into the final spoken
explanation (reduce) — recursing if the combined digests are still too long. This
replaces the old hard truncation at `summary_max_chars`, which silently dropped
the tail of anything longer than ~10-12 pages.
"""
from __future__ import annotations

import logging
import re

from readback.pipeline.extract import Article
from readback.pipeline.tones import ARTICLE as _ARTICLE_TONE, SUMMARY_WORD_CEILING

log = logging.getLogger("readback.pipeline")

# Default summary framing (article/blog tone). Source-aware tones pass their own
# `system` prompt into summarize_article; this is the fallback for a plain call.
_SUMMARY_SYSTEM = _ARTICLE_TONE.summary_system

# Map step: condense one section of a longer document into a faithful prose digest.
# These are intermediate (fed to the reduce step), so no spoken framing — just the
# content, tightened. The reduce step gives it the final spoken voice.
_MAP_SYSTEM = (
    "You are condensing one section of a longer document so it can later be "
    "combined into a single explanation. Capture the key ideas, facts, names, and "
    "arguments of THIS section faithfully, in plain prose. Don't invent anything, "
    "and don't add meta commentary like 'this section discusses' — just write the "
    "condensed content. Keep it tight but don't drop important specifics."
)

_PARA_SPLIT = re.compile(r"\n{2,}")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_MAX_REDUCE_DEPTH = 3


def _batches(text: str, max_chars: int) -> list[str]:
    """Pack `text` into ≤`max_chars` batches, preferring paragraph then sentence
    boundaries; a single over-long sentence is hard-cut as a last resort."""
    # Break into units no larger than a batch: paragraphs, falling back to
    # sentences for any paragraph that's itself too long.
    units: list[str] = []
    for para in _PARA_SPLIT.split(text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            units.append(para)
        else:
            units.extend(s.strip() for s in _SENT_SPLIT.split(para) if s.strip())

    batches: list[str] = []
    cur = ""
    for u in units:
        if len(u) > max_chars:
            # A single sentence longer than a whole batch — hard-split it.
            if cur:
                batches.append(cur)
                cur = ""
            for i in range(0, len(u), max_chars):
                batches.append(u[i:i + max_chars])
            continue
        if cur and len(cur) + 2 + len(u) > max_chars:
            batches.append(cur)
            cur = u
        else:
            cur = f"{cur}\n\n{u}" if cur else u
    if cur:
        batches.append(cur)
    return batches


def _summarize_once(llm, title: str, body: str, system: str, truncated: bool = False,
                    source_words: int | None = None) -> str:
    """Single spoken-explanation pass over `body` with the given `system` framing.

    The word count is spelled out to the model as a concrete length anchor — an
    abstract "don't pad" instruction wasn't enough on its own to stop the model
    padding short articles out toward the 250-word ceiling (it has no sense of
    "short" without a number to calibrate against). `source_words` overrides the
    count when `body` isn't the original source: the map-reduce reduce step
    passes condensed digests, and anchoring to *their* length would mis-calibrate
    the target on exactly the long inputs map-reduce exists for."""
    word_count = source_words if source_words is not None else len(body.split())
    user = (
        f"Title: {title}\n\n"
        f"Article{' (truncated)' if truncated else ''} ({word_count} words):\n{body}\n\n"
        "Give the spoken explanation now."
    )
    return llm.oneshot(system, user).strip()


def _trim_to_word_ceiling(text: str, ceiling: int = SUMMARY_WORD_CEILING) -> str:
    """Hard-enforce the tone prompts' word ceiling at a sentence boundary. The
    prompt's HARD LIMIT is advisory — the model still overshoots on long sources
    (measured 313 words from a 3,446-word article) — and every word past the
    ceiling is paid for again in synthesis time. Always keeps at least one
    sentence."""
    kept: list[str] = []
    words = 0
    for sent in _SENT_SPLIT.split(text.strip()):
        n = len(sent.split())
        if kept and words + n > ceiling:
            break
        kept.append(sent)
        words += n
    trimmed = " ".join(kept)
    if len(trimmed) < len(text.strip()):
        log.info("summary trimmed to the %d-word ceiling: %d -> %d words",
                 ceiling, len(text.split()), words)
    return trimmed


def summarize_article(
    llm, article: Article, max_chars: int = 60000, progress=None, system: str | None = None,
) -> str:
    """Produce a spoken-style summary/explanation of `article`.

    `system` selects the framing (a source-aware tone prompt); defaults to the
    article/blog tone. Fits in one pass when `len(text) <= max_chars`; otherwise
    map-reduces so the whole input (e.g. a full book scan) is covered rather than
    truncated. An optional `progress(done, total)` callback fires per batch during
    the map phase.
    """
    system = system or _SUMMARY_SYSTEM
    body = article.text
    if len(body) <= max_chars:
        if progress:
            progress(0, 1)
        summary = _summarize_once(llm, article.title, body, system,
                                  source_words=article.word_count)
        if progress:
            progress(1, 1)
        log.info("summary: %d words from %d-word article (single pass)",
                 len(summary.split()), article.word_count)
        return _trim_to_word_ceiling(summary) if summary else article.text

    summary = _map_reduce(llm, article.title, body, max_chars, system, progress=progress,
                          source_words=article.word_count)
    log.info("summary: %d words from %d-word article (map-reduce)",
             len(summary.split()), article.word_count)
    return _trim_to_word_ceiling(summary) if summary else article.text


def _map_reduce(llm, title: str, body: str, max_chars: int, system: str,
                depth: int = 0, progress=None, source_words: int | None = None) -> str:
    batches = _batches(body, max_chars)
    if len(batches) == 1:
        if progress:
            progress(0, 1)
        out = _summarize_once(llm, title, batches[0], system, source_words=source_words)
        if progress:
            progress(1, 1)
        return out

    log.info("map-reduce summary: %d batches (depth %d)", len(batches), depth)
    total = len(batches)
    partials: list[str] = []
    for i, batch in enumerate(batches):
        if progress:
            progress(i, total)
        digest = llm.oneshot(_MAP_SYSTEM, f"Section {i + 1} of {total}:\n\n{batch}").strip()
        if digest:
            partials.append(digest)
    if progress:
        progress(total, total)

    combined = "\n\n".join(partials)
    if not combined:
        return ""
    # The combined digests may still overflow context (many batches) — recurse,
    # depth-limited so a pathological input can't loop forever. The final reduce
    # uses the tone's `system` framing; intermediate maps stay tone-agnostic.
    # `source_words` (the ORIGINAL source's count, not the digests') rides along
    # so the length anchor stays calibrated to what the listener actually asked
    # to have summarized.
    if len(combined) > max_chars and depth < _MAX_REDUCE_DEPTH:
        return _map_reduce(llm, title, combined, max_chars, system, depth + 1,
                           source_words=source_words)
    return _summarize_once(llm, title, combined, system, source_words=source_words)
