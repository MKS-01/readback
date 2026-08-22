"""Feed picks: the newest posts from the sites you read, without a browser.

Configured under `reader.feeds` (config.yaml), each source is just the URL of a
blog's index page. Turning that into "here are the 3 latest things" is a
two-tier fetch, because roughly half of modern blogs have quietly dropped RSS:

  1. **Feed** — autodiscovery (`<link rel="alternate" type="application/rss+xml">`)
     on the index page, then a short list of conventional paths (`/feed`,
     `/rss.xml`, `/feeds/posts/default`, …). Parsed with stdlib ElementTree —
     RSS 2.0 `channel/item` and Atom `entry` both. Gives real publish dates.
  2. **HTML index scrape** — no feed (e.g. claude.com/blog): collect the links
     that sit under the index's own path (`/blog/…`), in document order, which
     on every blog index means newest first. No dates; the anchor text is
     usually a "Read more" button, so titles come from the slug.

⚠ No new dependency: `urllib` + `xml.etree` + regex, all stdlib. This module is
network-only glue plus pure parsing helpers — the parsing half is what the tests
cover (tests/test_feeds.py); the fetching half is exercised by actually running it.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse

log = logging.getLogger("readback.feeds")

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Conventional feed locations, tried in order when autodiscovery finds nothing.
_FEED_PATHS = ("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml",
               "/index.xml", "/feeds/posts/default")

_TIMEOUT = 12.0          # per HTTP request; a slow site must not stall the picks
_PER_SOURCE = 5          # items kept per source before interleaving


@dataclass
class FeedItem:
    """One post: enough to show a pick line and start a read."""
    title: str
    url: str
    source: str                       # display name (the site's host, trimmed)
    published: Optional[str] = None   # ISO-8601, or None for scraped indexes

    def to_dict(self) -> dict:
        return asdict(self)


# ── HTTP ────────────────────────────────────────────────────────────────────

def _get(url: str, timeout: float = _TIMEOUT) -> str:
    """GET `url` with a browser UA (many sites 403 anything else)."""
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read().decode("utf-8", errors="replace")


# ── Pure parsing helpers (unit-tested) ──────────────────────────────────────

_ALT_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_ATTR_RE = re.compile(r"""(\w[\w:-]*)\s*=\s*["']([^"']*)["']""")
_FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json")


def discover_feed_url(html: str, base_url: str) -> Optional[str]:
    """The page's declared feed, from `<link rel="alternate" type="…rss+xml">`.

    ⚠ Matches on the TYPE, not on `rel="alternate"` alone: a `rel=alternate`
    link is also how sites declare translations (claude.com lists a dozen
    hreflang alternates), and following one of those would fetch a localized
    HTML page and parse zero items.
    """
    for tag in _ALT_LINK_RE.findall(html):
        attrs = {k.lower(): v for k, v in _ATTR_RE.findall(tag)}
        if attrs.get("type", "").lower() in _FEED_TYPES and attrs.get("href"):
            return urljoin(base_url, attrs["href"])
    return None


def _text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_date(raw: str) -> Optional[str]:
    """RFC-822 (RSS) or ISO-8601 (Atom) → a normalized ISO-8601 string."""
    raw = (raw or "").strip()
    if not raw:
        return None
    from datetime import datetime
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(raw).isoformat()
    except Exception:
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except Exception:
        return None


def parse_feed(xml_text: str, source: str, base_url: str = "") -> list[FeedItem]:
    """Parse RSS 2.0 or Atom into FeedItems, newest-first as the feed lists them.

    Namespaces are stripped rather than declared, so an Atom feed that uses a
    non-standard prefix still parses. Returns [] on anything unparseable — a
    broken feed is a source that contributes no picks, never an error.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text.strip())
    except Exception:
        return []

    items: list[FeedItem] = []
    for el in root.iter():
        if _strip_ns(el.tag) not in ("item", "entry"):
            continue
        title = url = ""
        published = None
        for child in el:
            tag = _strip_ns(child.tag)
            if tag == "title" and not title:
                title = _text(child)
            elif tag == "link":
                # RSS puts the URL in the element text; Atom in href, and may
                # list several links (alternate = the post, others = comments).
                href = child.get("href")
                if href:
                    rel = (child.get("rel") or "alternate").lower()
                    if rel == "alternate" and not url:
                        url = href
                elif not url:
                    url = _text(child)
            elif tag in ("pubdate", "published", "updated", "date") and published is None:
                published = parse_date(_text(child))
        if not url or not title:
            continue
        items.append(FeedItem(
            title=title,
            url=urljoin(base_url, url.strip()),
            source=source,
            published=published,
        ))
    return items


_SLUG_SMALL = {"a", "an", "the", "and", "or", "but", "for", "nor", "of", "in",
               "on", "at", "to", "from", "by", "with", "as", "is", "are", "your"}


def title_from_slug(slug: str) -> str:
    """`artifacts-in-claude-code` → `Artifacts in Claude Code`.

    Blog indexes wrap their post links in a "Read more" button, so the anchor
    text is worthless and the slug is the only title available before fetching
    the post itself (which we are NOT doing for a list of picks).
    """
    words = [w for w in re.split(r"[-_/]+", slug.strip("/")) if w]
    out = []
    for i, w in enumerate(words):
        low = w.lower()
        out.append(low if (i and low in _SLUG_SMALL) else low[:1].upper() + low[1:])
    return " ".join(out) or slug


_ANCHOR_RE = re.compile(r"<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
# Anchor text that is a button, not a headline.
_GENERIC_ANCHOR = re.compile(
    r"^(read|learn|see|view|find out)( more| now)?|^more$|^continue|^→|^»", re.I
)


def scrape_index_links(html: str, index_url: str, limit: int = _PER_SOURCE,
                       source: Optional[str] = None) -> list[FeedItem]:
    """Feed-less fallback: post links under the index's own path, in document order.

    A blog index lists newest first, so document order IS recency here — there
    are no dates to sort by. Links are kept only when they sit one level deeper
    than the index path (`/blog/` → `/blog/some-post`, not `/blog/tag/x` two
    levels down and not `/pricing`), deduped, and titled from their anchor text
    when that text looks like a headline rather than a "Read more" button.
    """
    base = urlparse(index_url)
    prefix = base.path.rstrip("/") + "/"
    source = source or _source_name(index_url)
    seen: set[str] = set()
    items: list[FeedItem] = []

    for href, inner in _ANCHOR_RE.findall(html):
        abs_url = urljoin(index_url, href.split("?")[0])
        p = urlparse(abs_url)
        if p.netloc != base.netloc or not p.path.startswith(prefix):
            continue
        tail = p.path[len(prefix):].strip("/")
        if not tail or "/" in tail:
            continue                       # the index itself, or a deeper page
        if abs_url in seen:
            continue
        seen.add(abs_url)
        text = re.sub(r"\s+", " ", _TAG_RE.sub(" ", inner)).strip()
        title = text if (len(text) > 15 and not _GENERIC_ANCHOR.match(text)) else title_from_slug(tail)
        items.append(FeedItem(title=title, url=abs_url, source=source))
        if len(items) >= limit:
            break
    return items


def pick_key(url: str) -> str:
    """Identity of a post for the read/unread check on the picks list.

    ⚠ Query strings differ between how a feed hands you a URL and how you'd
    paste it (Medium appends `?source=rss----…`), so the key is scheme + host +
    path — otherwise an article you've already heard reads as unread forever
    and keeps its slot in the picks.
    """
    from urllib.parse import urlsplit

    p = urlsplit(url.strip())
    return f"{p.scheme}://{p.netloc}{p.path.rstrip('/')}".lower()


def _source_name(url: str) -> str:
    """Display name for a source: the host without `www.`/TLD noise."""
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def interleave(per_source: list[list[FeedItem]], limit: int) -> list[FeedItem]:
    """Round-robin the sources, newest-first within each round.

    ⚠ Diversity beats strict recency here: a site that posts daily would own all
    3 picks if we sorted purely by date, and the point of the picks list is to
    show you what's new across the sites you follow. Round 1 is therefore each
    source's newest post (ordered by date among themselves, undated last), round
    2 each source's second-newest, and so on.
    """
    picks: list[FeedItem] = []
    depth = max((len(s) for s in per_source), default=0)
    for rank in range(depth):
        rung = [s[rank] for s in per_source if rank < len(s)]
        dated = sorted((i for i in rung if i.published),
                       key=lambda i: i.published, reverse=True)
        picks.extend(dated + [i for i in rung if not i.published])
        if len(picks) >= limit:
            break
    return picks[:limit]


# ── Fetching ────────────────────────────────────────────────────────────────

def fetch_source(url: str, name: Optional[str] = None,
                 limit: int = _PER_SOURCE, timeout: float = _TIMEOUT) -> list[FeedItem]:
    """Newest posts for one configured source (feed if there is one, else scrape)."""
    source = name or _source_name(url)
    html = ""
    # A source may be the feed itself — parse it directly rather than guessing.
    try:
        body = _get(url, timeout)
    except Exception as e:
        log.warning("feed source unreachable: %s (%s)", url, e)
        return []
    if body.lstrip()[:200].lstrip().startswith("<?xml") or "<rss" in body[:400].lower():
        items = parse_feed(body, source, url)
        if items:
            return items[:limit]
    html = body

    feed_url = discover_feed_url(html, url)
    candidates = [feed_url] if feed_url else []
    root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    candidates += [urljoin(root + "/", p.lstrip("/")) for p in _FEED_PATHS]

    for cand in candidates:
        try:
            items = parse_feed(_get(cand, timeout), source, cand)
        except Exception:
            continue
        if items:
            log.info("feed for %s: %s (%d items)", source, cand, len(items))
            return items[:limit]

    items = scrape_index_links(html, url, limit, source)
    if items:
        log.info("no feed for %s — scraped %d links from the index", source, len(items))
    else:
        log.warning("no posts found for %s", source)
    return items


def latest(sources: list, limit: int = 3, per_source: int = _PER_SOURCE,
           timeout: float = _TIMEOUT) -> list[FeedItem]:
    """Top `limit` picks across every configured source, fetched in parallel.

    `sources` are `FeedSource`-shaped (`.url` / `.name`) or plain URL strings.
    A source that fails contributes nothing — the picks list degrades, never errors.
    """
    if not sources:
        return []
    pairs = [(getattr(s, "url", s), getattr(s, "name", None)) for s in sources]
    with ThreadPoolExecutor(max_workers=min(8, len(pairs))) as pool:
        results = list(pool.map(
            lambda p: fetch_source(p[0], p[1], per_source, timeout), pairs
        ))
    return interleave(results, limit)


class FeedCache:
    """Picks with a TTL, so opening the CLI doesn't re-crawl every blog.

    The CLI asks for picks on every launch and on `/feed`; the underlying blogs
    publish a few times a week. A short TTL keeps launch instant after the first
    fetch, and `latest(refresh=True)` (the `/feed` command) always re-crawls.
    """

    def __init__(self, sources: list, ttl_sec: float = 900.0):
        self.sources = sources
        self.ttl = ttl_sec
        self._items: list[FeedItem] = []
        self._at: float = 0.0

    # The crawl keeps everything it found, not just the N being displayed: the
    # caller filters out posts already in the read library, and each filtered
    # pick has to be backfilled from the pool rather than shrinking the list.
    POOL = 30

    def latest(self, limit: int = 3, refresh: bool = False) -> list[FeedItem]:
        return self.pool(refresh)[:limit]

    def pool(self, refresh: bool = False) -> list[FeedItem]:
        """The full cached crawl, newest-first in pick order."""
        fresh = self._items and (time.monotonic() - self._at) < self.ttl
        if refresh or not fresh:
            items = latest(self.sources, limit=self.POOL)
            if items or refresh:
                self._items, self._at = items, time.monotonic()
        return self._items
