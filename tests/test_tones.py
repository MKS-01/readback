"""Source-aware reading tones — classify_source + tone_for mapping (pure logic)."""
from readback.pipeline.extract import classify_source
from readback.pipeline.tones import ARTICLE, BOOK, tone_for


def test_url_classifies_as_article():
    assert classify_source("https://example.com/blog/post") == "article"


def test_image_path_classifies_as_book():
    assert classify_source("/Users/me/scan.jpg") == "book"


def test_glob_classifies_as_book():
    assert classify_source("~/Desktop/scan/page*.png") == "book"


def test_tone_for_maps_kind_to_tone():
    assert tone_for("book") is BOOK
    assert tone_for("article") is ARTICLE
    assert tone_for("") is ARTICLE


def test_book_tone_is_measured_article_is_livelier():
    assert BOOK.temperature < ARTICLE.temperature
