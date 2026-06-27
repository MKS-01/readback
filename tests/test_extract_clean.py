"""extract.py pure helpers — TTS scrubbing, fallback title, word count."""
from readback.pipeline.extract import Article, _clean_for_tts, _fallback_title


def test_strips_urls():
    assert "http" not in _clean_for_tts("See https://example.com/x for more.")


def test_strips_citation_markers_and_collapses_whitespace():
    assert _clean_for_tts("A claim[1] and another[12].") == "A claim and another."
    out = _clean_for_tts("Real line.\nhttps://only-a-url.example\nNext line.")
    assert out.splitlines() == ["Real line.", "Next line."]


def test_fallback_title_from_url_tail():
    assert _fallback_title("https://example.com/my-great-post/") == "my great post"
    assert _fallback_title("https://example.com/") == "example.com"


def test_article_word_count():
    assert Article(title="t", text="one two three", url="u").word_count == 3
