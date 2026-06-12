"""Article extraction: URL → clean {title, text} suitable for TTS.

Uses trafilatura (best-in-class boilerplate removal) to pull the main article
body out of arbitrary blog/news HTML, then lightly normalizes the text so the
TTS doesn't read URLs, citation markers, or stray markup aloud.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger("readback.pipeline")


class ExtractError(Exception):
    """Fetch failed or no readable article text was found."""


@dataclass
class Article:
    title: str
    text: str
    url: str

    @property
    def word_count(self) -> int:
        return len(self.text.split())


# Light TTS-prep scrubbing on top of trafilatura's already-clean text.
_URL_RE = re.compile(r"https?://\S+")
_CITATION_RE = re.compile(r"\[\d+\]")          # "[1]", "[12]" reference markers
_MULTISPACE_RE = re.compile(r"[ \t]+")
_MULTINEWLINE_RE = re.compile(r"\n{3,}")


def _clean_for_tts(text: str) -> str:
    text = _URL_RE.sub("", text)
    text = _CITATION_RE.sub("", text)
    text = _MULTISPACE_RE.sub(" ", text)
    text = _MULTINEWLINE_RE.sub("\n\n", text)
    # Drop lines that are now empty/whitespace-only after scrubbing.
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


def _fallback_title(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    tail = re.sub(r"[-_]+", " ", tail).strip()
    return tail or "Article"


# A realistic browser UA — trafilatura's default UA is blocked by many sites.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _download(url: str) -> str:
    """Fetch raw HTML, trying trafilatura first then a browser-UA urllib fallback
    (many sites 403 trafilatura's default agent)."""
    import trafilatura

    html = trafilatura.fetch_url(url)
    if html:
        return html
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (user-supplied URL)
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def fetch_article(url: str) -> Article:
    """Fetch `url` and return the extracted, TTS-ready article. Raises
    ExtractError on a failed fetch or when no article text is found."""
    import trafilatura

    url = (url or "").strip()
    if not url:
        raise ExtractError("empty URL")
    if not re.match(r"^https?://", url):
        url = "https://" + url

    try:
        downloaded = _download(url)
    except Exception as e:
        raise ExtractError(f"could not fetch the page at {url}: {e}") from e
    if not downloaded:
        raise ExtractError(f"could not fetch the page at {url}")

    text = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text or not text.strip():
        raise ExtractError("no readable article text found at that URL")

    title = ""
    try:
        md = trafilatura.extract_metadata(downloaded)
        if md and md.title:
            title = md.title
    except Exception:
        pass
    title = (title or _fallback_title(url)).strip()

    article = Article(title=title, text=_clean_for_tts(text), url=url)
    log.info("extracted %r (%d words) from %s", title, article.word_count, url)
    return article
