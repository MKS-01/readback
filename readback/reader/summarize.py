"""Summary / explainer mode: turn an extracted article into a spoken-friendly
explanation via the LLM. (Verbatim mode skips this and reads the text directly.)
"""
from __future__ import annotations

import logging

from readback.reader.extract import Article

log = logging.getLogger("readback.reader")

_SUMMARY_SYSTEM = (
    "You turn written articles into a clear spoken explanation for a listener. "
    "Explain the key ideas and why they matter in a natural, conversational "
    "narration — as if walking a friend through the piece. Lead with what the "
    "article is about, then the main points in a logical order, defining any term "
    "the first time it comes up. Be faithful to the source; don't invent facts. "
    "Since this is read aloud, use plain flowing sentences only — no markdown, no "
    "headings, no bullet points, no special characters. Aim for a tight, "
    "listenable length (roughly 8 to 15 sentences for a typical article)."
)


def summarize_article(llm, article: Article, max_chars: int = 16000) -> str:
    """Produce a spoken-style summary/explanation of `article`. Long articles are
    truncated to `max_chars` to stay within the model's context window."""
    body = article.text
    truncated = len(body) > max_chars
    if truncated:
        body = body[:max_chars]
    user = (
        f"Title: {article.title}\n\n"
        f"Article{' (truncated)' if truncated else ''}:\n{body}\n\n"
        "Give the spoken explanation now."
    )
    summary = llm.oneshot(_SUMMARY_SYSTEM, user).strip()
    log.info("summary: %d words from %d-word article", len(summary.split()),
             article.word_count)
    return summary or article.text
