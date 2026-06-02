"""Web search tool with a swappable provider interface.

Ships DuckDuckGo HTML scraping as the default — free, no API key, no signup.
Tavily and Brave are deliberately stubbed-not-implemented so the user can
plug them in later without changing call sites.

DDG's HTML endpoint returns a tiny static-rendered page; we use the standard
library's html.parser (no extra deps) and pull the first N result anchors
plus their snippet siblings.
"""
from __future__ import annotations

import html
import logging
import re
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urlencode, urlparse, parse_qs, unquote
from urllib.request import Request, urlopen

log = logging.getLogger("vox_tinker.tools.web_search")

# A real-browser UA stops DDG from returning the empty "JavaScript required"
# fallback page. The HTML endpoint is server-rendered so this is enough.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
_DDG_URL = "https://html.duckduckgo.com/html/"
_TIMEOUT = 6.0
_MAX_RESULTS = 5


class SearchResult:
    __slots__ = ("title", "url", "snippet")

    def __init__(self, title: str, url: str, snippet: str):
        self.title = title
        self.url = url
        self.snippet = snippet


class WebSearchProvider(Protocol):
    name: str

    def search(self, query: str, k: int = _MAX_RESULTS) -> list[SearchResult]: ...


class _DDGResultParser(HTMLParser):
    """Minimal parser that pulls out result blocks. DDG's HTML format has
    `<a class="result__a" href="...">title</a>` and `<a class="result__snippet">
    snippet</a>` siblings. Resilient to small layout drift via class-prefix
    matching.
    """

    def __init__(self) -> None:
        super().__init__()
        self.results: list[SearchResult] = []
        self._cur_url: str = ""
        self._cur_title_parts: list[str] = []
        self._cur_snippet_parts: list[str] = []
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag: str, attrs):
        if tag != "a":
            return
        a = dict(attrs)
        cls = (a.get("class") or "").strip()
        href = a.get("href") or ""
        if "result__a" in cls:
            self._flush_pending_title()
            self._cur_url = href
            self._in_title = True
            self._cur_title_parts = []
        elif "result__snippet" in cls:
            self._in_snippet = True
            self._cur_snippet_parts = []

    def handle_endtag(self, tag: str):
        if tag == "a":
            if self._in_title:
                self._in_title = False
            if self._in_snippet:
                self._in_snippet = False
                self._flush_pending_title()

    def handle_data(self, data: str):
        if self._in_title:
            self._cur_title_parts.append(data)
        elif self._in_snippet:
            self._cur_snippet_parts.append(data)

    def _flush_pending_title(self):
        if not self._cur_url and not self._cur_title_parts:
            return
        title = " ".join(self._cur_title_parts).strip()
        snippet = " ".join(self._cur_snippet_parts).strip()
        url = _normalize_ddg_href(self._cur_url)
        if title and url:
            self.results.append(SearchResult(title=title, url=url, snippet=snippet))
        self._cur_url = ""
        self._cur_title_parts = []
        self._cur_snippet_parts = []


def _normalize_ddg_href(href: str) -> str:
    """DDG returns wrapped URLs like `//duckduckgo.com/l/?uddg=<encoded>`.
    Unwrap to the actual target so the result is useful."""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        target = qs.get("uddg", [""])[0]
        if target:
            return unquote(target)
    return href


class DuckDuckGoProvider:
    name = "duckduckgo"

    def search(self, query: str, k: int = _MAX_RESULTS) -> list[SearchResult]:
        if not query.strip():
            return []
        data = urlencode({"q": query, "kl": "us-en"}).encode("utf-8")
        req = Request(
            _DDG_URL,
            data=data,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        try:
            with urlopen(req, timeout=_TIMEOUT) as resp:
                body_bytes = resp.read()
        except Exception as e:
            log.warning("DDG fetch failed: %s", e)
            return []
        body = body_bytes.decode("utf-8", errors="replace")
        # Strip script/style blocks before parsing so JS strings can't confuse
        # the lightweight HTMLParser.
        body = re.sub(r"<script[\s\S]*?</script>", "", body, flags=re.IGNORECASE)
        body = re.sub(r"<style[\s\S]*?</style>", "", body, flags=re.IGNORECASE)
        p = _DDGResultParser()
        try:
            p.feed(body)
        except Exception:
            log.exception("DDG parse failed")
            return []
        return p.results[:k]


class WebSearchTool:
    """Ollama-facing tool. Holds a swappable provider so a future Tavily/Brave
    backend slots in without touching `LLMClient`. The output is intentionally
    plain text — the assistant reads it and summarizes, rather than re-quoting
    a JSON blob the user would never want spoken aloud."""

    name = "web_search"
    schema = {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the public web for current information. Use this when "
                "the user asks about recent events, news, prices, definitions, "
                "or anything you don't reliably know."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                },
                "required": ["query"],
            },
        },
    }

    def __init__(self, provider: WebSearchProvider):
        self.provider = provider

    def run(self, args: dict[str, Any]) -> str:
        query = (args.get("query") or "").strip()
        if not query:
            return "[web_search] no query provided"
        results = self.provider.search(query)
        if not results:
            return f"[web_search] no results for {query!r}"
        lines = [f"Top results for: {query}"]
        for i, r in enumerate(results, 1):
            snippet = html.unescape(r.snippet)
            lines.append(f"{i}. {r.title} — {snippet} ({r.url})")
        return "\n".join(lines)


def build_default_provider(name: str) -> WebSearchProvider:
    """Factory keyed off cfg.tools.web_search_provider. Today only DDG ships;
    additional providers slot in here without other call sites changing."""
    if name == "duckduckgo":
        return DuckDuckGoProvider()
    raise ValueError(f"Unknown web search provider {name!r}")
