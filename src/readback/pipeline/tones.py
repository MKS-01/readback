"""Reading tones — source-aware framing + delivery.

A *tone* bundles how a piece is summarized (the LLM system prompt) with how it's
spoken (the CSM sampling temperature). The source type picks the tone
automatically: a URL reads as a lively article/blog explainer; a scanned image or
folder reads as a book — narrated in a measured voice, opening by naming the
chapter or topic. Add a third tone (e.g. a technical-paper voice) by defining
another `Tone` and extending `tone_for`.

Delivery varies by temperature only — the user's chosen voice (`/voice`) is left
untouched. A tone's `temperature` is the *base* delivery setting; `speak.py`'s
`_expressive_temperature` nudges it per chunk (punctuation-driven) so expression
shifts with the content instead of staying flat for the whole read.
"""
from __future__ import annotations

from dataclasses import dataclass

# The spoken-summary length ceiling, in words. Baked into every tone prompt AND
# hard-enforced post-hoc by summarize_article's sentence-boundary trim — the
# prompt alone is advisory (the model overshoots on long sources), and every
# word past the ceiling is paid for again in synthesis time.
SUMMARY_WORD_CEILING = 250

# Length policy shared by every tone — one source of truth so the rules can't
# drift between prompts. {src} names what's being summarized, {out} what the
# model produces (e.g. article/explanation, passage/narration).
_LENGTH_RULES = (
    "The {src}'s word count is given to you — use it: your {out} should usually "
    "land at roughly half that many words, and should almost never exceed it. "
    f"{SUMMARY_WORD_CEILING} words is a CEILING, not a target — reserve it for a "
    "{src} that is itself long; a {src} of a few hundred words should get "
    "well under 150. Never add generic wrap-up or editorializing "
    "sentences that aren't grounded in a specific fact from the {src} (e.g. broad "
    "claims about 'a significant shift' or 'a smoother transition') just to fill "
    "space — every sentence must carry real information from the {src}, and it's "
    "fine to stop early once you've covered the key points. HARD LIMIT: never "
    f"exceed {SUMMARY_WORD_CEILING} words (roughly 10 to 15 sentences). "
)
_PLAIN_PROSE_RULE = (
    "Use plain flowing sentences only — no markdown, no headings, no bullet "
    "points, no special characters."
)

# Article / blog: turn written prose into a clear spoken explanation. (This is the
# prompt that lived in summarize.py as _SUMMARY_SYSTEM before tones existed.)
_ARTICLE_SYSTEM = (
    "You turn written articles into a SHORT spoken explanation for a listener — a "
    "concise briefing of the gist, NOT a retelling. Lead with what the article is "
    "about, then its main points in a logical order, defining any term the first "
    "time it comes up. Be faithful to the source; don't invent facts and don't pad. "
    + _LENGTH_RULES.format(src="article", out="explanation") +
    "Since this is read aloud, write it the way a "
    "person would actually explain it out loud, not a flat list of facts: vary "
    "sentence length and rhythm, use a short punchy sentence for a striking point "
    "and a longer one to connect ideas, and let a genuinely surprising or notable "
    "fact carry natural emphasis (a real exclamation or question where it truly "
    "fits) rather than reading every sentence in the same even register. "
    + _PLAIN_PROSE_RULE
)

# Book passage: narrate a scanned chapter/section. Open by naming the chapter or
# topic (the Title carries it, distilled from the page's opening lines), then walk
# through the content faithfully in a calmer, reading-aloud cadence.
_BOOK_SYSTEM = (
    "You are narrating a passage from a book to a listener. Open by naming the "
    "chapter or topic this passage covers (the title tells you), then walk through "
    "its content in a clear, measured, reading-aloud narration. Explain the ideas "
    "and how they develop in order, defining terms as they appear. Be faithful to "
    "the text; don't invent anything beyond what the passage says, and don't pad. "
    + _LENGTH_RULES.format(src="passage", out="narration") +
    "Since this is read aloud, narrate it the way a person reads a book out loud, "
    "not a flat list of facts: vary sentence length and rhythm with the material, "
    "and let a genuinely pivotal or striking moment carry natural emphasis rather "
    "than reading every line in the same even register. "
    + _PLAIN_PROSE_RULE
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
