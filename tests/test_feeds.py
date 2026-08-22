"""Feed picks — the parsing half (no network).

Everything here is pure text → FeedItem: RSS/Atom parsing, feed autodiscovery,
the HTML-index fallback for feed-less blogs, and the round-robin that turns
per-source lists into the CLI's numbered picks.
"""
from readback.pipeline.feeds import (
    FeedItem,
    pick_key,
    discover_feed_url,
    interleave,
    parse_date,
    parse_feed,
    scrape_index_links,
    title_from_slug,
)

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Netflix TechBlog</title>
  <item>
    <title>A Tale of Two Autoscalers</title>
    <link>https://blog.example.com/two-autoscalers</link>
    <pubDate>Thu, 21 Aug 2026 16:01:01 GMT</pubDate>
  </item>
  <item>
    <title>Older Post</title>
    <link>https://blog.example.com/older</link>
    <pubDate>Mon, 04 Aug 2026 09:00:00 GMT</pubDate>
  </item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Android Developers Blog</title>
  <entry>
    <title>Broader memory limits</title>
    <link rel="replies" href="https://blog.example.com/comments"/>
    <link rel="alternate" href="https://blog.example.com/memory-limits"/>
    <published>2026-08-19T12:00:00-07:00</published>
  </entry>
</feed>"""


def test_parse_rss_items():
    items = parse_feed(RSS, "netflix")
    assert [i.title for i in items] == ["A Tale of Two Autoscalers", "Older Post"]
    assert items[0].url == "https://blog.example.com/two-autoscalers"
    assert items[0].source == "netflix"
    assert items[0].published.startswith("2026-08-21T16:01:01")


def test_parse_atom_takes_the_alternate_link():
    items = parse_feed(ATOM, "android")
    assert len(items) == 1
    # `rel="replies"` comes first in the document — the post URL is the alternate.
    assert items[0].url == "https://blog.example.com/memory-limits"
    assert items[0].published.startswith("2026-08-19T12:00:00")


def test_parse_feed_on_garbage_returns_no_items():
    assert parse_feed("<html><body>not a feed</body></html>", "x") == []
    assert parse_feed("", "x") == []


def test_relative_links_resolve_against_the_feed_url():
    rss = RSS.replace("https://blog.example.com/two-autoscalers", "/two-autoscalers")
    items = parse_feed(rss, "s", "https://blog.example.com/feed")
    assert items[0].url == "https://blog.example.com/two-autoscalers"


def test_discover_feed_ignores_hreflang_alternates():
    # ⚠ claude.com declares a dozen `rel=alternate` translation links; matching
    # on rel alone would "discover" a localized HTML page as the feed.
    html = """
      <link rel="alternate" hrefLang="ja-JP" href="https://x.com/ja/blog"/>
      <link rel="alternate" type="application/rss+xml" href="/feed.xml"/>
    """
    assert discover_feed_url(html, "https://x.com/blog") == "https://x.com/feed.xml"


def test_discover_feed_returns_none_when_absent():
    assert discover_feed_url("<html><head></head></html>", "https://x.com/") is None


INDEX = """
<html><body>
  <a href="/pricing">Pricing</a>
  <a href="/blog">All posts</a>
  <a href="/blog/tag/engineering">Engineering</a>
  <a href="/blog/artifacts-in-claude-code"><span>Read more</span></a>
  <a href="/blog/harnessing-the-model?utm=x">Harnessing the model in production</a>
  <a href="/blog/artifacts-in-claude-code">Read more</a>
  <a href="https://elsewhere.com/blog/other">Other site</a>
</body></html>
"""


def test_scrape_index_keeps_only_sibling_post_links():
    items = scrape_index_links(INDEX, "https://claude.com/blog", limit=5)
    assert [i.url for i in items] == [
        "https://claude.com/blog/artifacts-in-claude-code",
        "https://claude.com/blog/harnessing-the-model",
    ]


def test_scrape_index_titles_fall_back_to_the_slug():
    items = scrape_index_links(INDEX, "https://claude.com/blog", limit=5)
    # "Read more" is a button, not a headline → slug; real anchor text is kept.
    assert items[0].title == "Artifacts in Claude Code"
    assert items[1].title == "Harnessing the model in production"
    assert items[0].published is None


def test_scrape_index_respects_the_limit():
    assert len(scrape_index_links(INDEX, "https://claude.com/blog", limit=1)) == 1


def test_title_from_slug_lowercases_small_words_only_after_the_first():
    assert title_from_slug("the-state-of-a-thing") == "The State of a Thing"
    assert title_from_slug("/preparing-your-app/") == "Preparing your App"


def test_parse_date_handles_rfc822_iso_and_junk():
    assert parse_date("Thu, 21 Aug 2026 16:01:01 GMT").startswith("2026-08-21")
    assert parse_date("2026-08-19T12:00:00Z").startswith("2026-08-19")
    assert parse_date("last tuesday") is None
    assert parse_date("") is None


def _item(title, pub=None, source="s"):
    return FeedItem(title=title, url=f"https://x/{title}", source=source, published=pub)


def test_interleave_takes_one_from_each_source_before_seconds():
    a = [_item("a1", "2026-08-01"), _item("a2", "2026-07-01")]
    b = [_item("b1", "2026-08-20"), _item("b2", "2026-07-20")]
    # Round 1 is each source's newest (b1 newer than a1), THEN the second-newest.
    assert [i.title for i in interleave([a, b], 3)] == ["b1", "a1", "b2"]


def test_interleave_puts_undated_sources_last_within_a_round():
    a = [_item("dated", "2026-08-01")]
    b = [_item("undated")]
    assert [i.title for i in interleave([b, a], 2)] == ["dated", "undated"]


def test_interleave_handles_empty_and_short_sources():
    assert interleave([], 3) == []
    assert [i.title for i in interleave([[], [_item("only")]], 3)] == ["only"]


def test_pick_key_ignores_query_and_trailing_slash():
    # A Medium feed hands out `?source=rss----…`; the library stores whatever
    # was read. Both must resolve to the same post or it never counts as read.
    assert pick_key("https://blog.example.com/post?source=rss----abc") == pick_key(
        "https://blog.example.com/post/"
    )


def test_pick_key_separates_different_posts_and_hosts():
    assert pick_key("https://a.com/post") != pick_key("https://a.com/other")
    assert pick_key("https://a.com/post") != pick_key("https://b.com/post")
