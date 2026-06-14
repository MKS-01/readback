"""extract.py pure helpers — TTS scrubbing, fallback title, word count."""
from readback.pipeline.extract import Article, _clean_for_tts, _fallback_title


def test_strips_urls():
    assert "http" not in _clean_for_tts("See https://example.com/x for more.")


def test_strips_numeric_citation_markers():
    assert _clean_for_tts("A claim[1] and another[12].") == "A claim and another."


def test_collapses_runs_of_spaces_and_blank_lines():
    out = _clean_for_tts("a    b\n\n\n\nc")
    assert "    " not in out
    assert "\n\n\n" not in out


def test_drops_empty_lines_left_after_scrubbing():
    # A line that is only a URL becomes empty and should be removed entirely.
    out = _clean_for_tts("Real line.\nhttps://only-a-url.example\nNext line.")
    assert out.splitlines() == ["Real line.", "Next line."]


def test_fallback_title_from_url_tail():
    assert _fallback_title("https://example.com/my-great-post/") == "my great post"
    assert _fallback_title("https://example.com/2026/the_big_one") == "the big one"
    # A bare domain has no path tail, so it falls back to the host itself.
    assert _fallback_title("https://example.com/") == "example.com"


def test_article_word_count():
    assert Article(title="t", text="one two three", url="u").word_count == 3
    assert Article(title="t", text="   ", url="u").word_count == 0
