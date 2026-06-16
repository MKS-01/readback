"""Source-aware reading tones — classify_source + tone_for mapping (pure logic)."""
import pytest

from readback.pipeline.extract import classify_source
from readback.pipeline.tones import ARTICLE, BOOK, tone_for


@pytest.mark.parametrize("url", [
    "https://example.com/blog/post",
    "http://news.site/article-123",
    "example.com/some/path",
])
def test_urls_classify_as_article(url):
    assert classify_source(url) == "article"


@pytest.mark.parametrize("path", [
    "~/Desktop/page.png",
    "/Users/me/scan.jpg",
    "photo.heic",
    "shot.JPEG",
])
def test_image_paths_classify_as_book(path):
    assert classify_source(path) == "book"


@pytest.mark.parametrize("pattern", [
    "~/Desktop/scan/page*.png",
    "/Users/me/book/*.jpg",
    "pages/p?.png",
])
def test_globs_classify_as_book(pattern):
    assert classify_source(pattern) == "book"


def test_tone_for_maps_kind_to_tone():
    assert tone_for("book") is BOOK
    assert tone_for("article") is ARTICLE
    # Unknown / empty kinds fall back to the article tone.
    assert tone_for("") is ARTICLE
    assert tone_for("whatever") is ARTICLE


def test_book_tone_is_measured_article_is_livelier():
    # The whole point: a book reads calmer than an article.
    assert BOOK.temperature < ARTICLE.temperature


def test_tones_carry_distinct_framing():
    assert BOOK.summary_system != ARTICLE.summary_system
    assert "book" in BOOK.summary_system.lower()
