"""Reading tones — source-aware framing + delivery.

A *tone* bundles how a piece is summarized (the LLM system prompt) with how it's
spoken (the CSM sampling temperature). The source type picks the tone
automatically: a URL reads as a lively article/blog explainer; a scanned image or
folder reads as a book — narrated in a measured voice, opening by naming the
chapter or topic. Add a third tone (e.g. a technical-paper voice) by defining
another `Tone` and extending `tone_for`.

Delivery varies by temperature only — the user's chosen voice (`/voice`) is left
untouched.
"""
from __future__ import annotations

from dataclasses import dataclass

# Article / blog: turn written prose into a clear spoken explanation. (This is the
# prompt that lived in summarize.py as _SUMMARY_SYSTEM before tones existed.)
_ARTICLE_SYSTEM = (
    "You turn written articles into a clear spoken explanation for a listener. "
    "Explain the key ideas and why they matter in a natural, conversational "
    "narration — as if walking a friend through the piece. Lead with what the "
    "article is about, then the main points in a logical order, defining any term "
    "the first time it comes up. Be faithful to the source; don't invent facts. "
    "Since this is read aloud, use plain flowing sentences only — no markdown, no "
    "headings, no bullet points, no special characters. Aim for a tight, "
    "listenable length (roughly 8 to 15 sentences for a typical article)."
)

# Book passage: narrate a scanned chapter/section. Open by naming the chapter or
# topic (the Title carries it, distilled from the page's opening lines), then walk
# through the content faithfully in a calmer, reading-aloud cadence.
_BOOK_SYSTEM = (
    "You are narrating a passage from a book to a listener. Open by naming the "
    "chapter or topic this passage covers (the title tells you), then walk through "
    "its content in a clear, measured, reading-aloud narration. Explain the ideas "
    "and how they develop in order, defining terms as they appear. Be faithful to "
    "the text; don't invent anything beyond what the passage says. Since this is "
    "read aloud, use plain flowing sentences only — no markdown, no headings, no "
    "bullet points, no special characters."
)


@dataclass(frozen=True)
class Tone:
    name: str
    summary_system: str   # LLM system prompt for Summary mode
    temperature: float     # CSM delivery temperature (lower = composed/measured)


# Livelier explainer for short-form web prose.
ARTICLE = Tone("article", _ARTICLE_SYSTEM, 0.8)
# Composed, measured narration for book scans.
BOOK = Tone("book", _BOOK_SYSTEM, 0.6)


def tone_for(kind: str) -> Tone:
    """Map a source kind ('book' | 'article') to its reading tone (default ARTICLE)."""
    return BOOK if kind == "book" else ARTICLE
