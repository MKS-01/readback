"""Ask the LLM to pick a single folder-safe slug that summarizes a conversation.

Fires at session end to decide where the markdown transcript lands inside the
Obsidian vault. The output is regex-clamped so a hallucinated path traversal
or punctuation-laden answer can't escape the vault root.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # avoid an import cycle with llm/client.py at module load
    from local_tts.llm.client import LLMClient

log = logging.getLogger("local_tts.memory.topic")

UNSORTED = "unsorted"

# Lowercase, hyphenated, 1–32 chars. Anything outside this regex (path
# separators, control chars, parens, etc.) falls back to UNSORTED.
_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

_TOPIC_SYSTEM_PROMPT = (
    "You categorize conversations into a single folder name. "
    "Read the conversation and respond with ONLY a short folder slug. "
    "Use 1 to 4 words separated by hyphens. Lowercase letters and digits only. "
    "No punctuation, no quotes, no explanation. "
    "Examples: project-planning, recipe-ideas, debug-session, travel-notes."
)


def _sanitize(raw: str) -> str:
    """Clean an LLM topic response into a safe filesystem slug.

    Strips quotes/whitespace, lowercases, replaces internal whitespace with
    hyphens, drops anything outside [a-z0-9-]. Returns UNSORTED if the result
    fails validation.
    """
    if not raw:
        return UNSORTED
    s = raw.strip().strip("\"'").strip()
    # Take the first line — chat models sometimes preamble before the slug.
    s = s.split("\n", 1)[0].strip()
    s = s.lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if not _SLUG_OK.match(s):
        return UNSORTED
    return s


def propose_topic(
    llm: "LLMClient",
    transcript_summary: str,
    *,
    model_override: Optional[str] = None,
) -> str:
    """Return a folder slug for the given transcript. Never raises.

    Uses the LLM's active Ollama client (cheap reuse) and a temperature of 0
    for determinism. `model_override` lets the caller force a smaller model
    for cost/latency; defaults to the chat model.
    """
    if not transcript_summary.strip():
        return UNSORTED
    model = model_override or llm.cfg.model
    try:
        response = llm._client.chat(
            model=model,
            messages=[
                {"role": "system", "content": _TOPIC_SYSTEM_PROMPT},
                {"role": "user", "content": transcript_summary},
            ],
            stream=False,
            options={"temperature": 0.0},
        )
        raw = (response.message.content or "").strip()
        slug = _sanitize(raw)
        return slug
    except Exception:
        log.exception("topic classification failed; falling back to unsorted")
        return UNSORTED
