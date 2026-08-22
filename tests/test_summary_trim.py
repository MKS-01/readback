"""_trim_to_word_ceiling — post-hoc enforcement of the spoken-summary ceiling."""
from readback.pipeline.summarize import _trim_to_word_ceiling
from readback.pipeline.tones import SUMMARY_WORD_CEILING


def test_short_summary_is_untouched():
    text = "First sentence here. Second sentence follows!"
    assert _trim_to_word_ceiling(text) == text


def test_overshoot_is_trimmed_at_a_sentence_boundary():
    sent = "This sentence carries exactly ten words of real content padding."
    text = " ".join([sent] * 40)          # 400 words, well over the ceiling
    trimmed = _trim_to_word_ceiling(text)
    n = len(trimmed.split())
    assert n <= SUMMARY_WORD_CEILING
    assert trimmed.endswith("padding.")   # cut on a sentence boundary, not mid-sentence
    assert n == (SUMMARY_WORD_CEILING // 10) * 10


def test_single_giant_sentence_is_kept():
    text = "word " * 300
    text = text.strip() + "."
    assert _trim_to_word_ceiling(text) == text


def test_custom_ceiling():
    text = "One two three. Four five six. Seven eight nine."
    assert _trim_to_word_ceiling(text, ceiling=6) == "One two three. Four five six."


def test_trim_preserves_paragraph_breaks():
    """⚠ speak.py takes its pause lengths from these breaks — the trim used to
    reflow the whole summary into one line with ' '.join()."""
    text = "One two three. Four five six.\n\nSeven eight nine. Ten."
    assert "\n\n" in _trim_to_word_ceiling(text)


def test_trim_stops_at_the_ceiling_across_paragraphs():
    text = "One two three.\n\nFour five six.\n\nSeven eight nine."
    assert _trim_to_word_ceiling(text, ceiling=6) == "One two three.\n\nFour five six."


def test_trim_keeps_one_sentence_even_when_it_exceeds_the_ceiling():
    text = "One two three four five six seven.\n\nSecond paragraph here."
    assert _trim_to_word_ceiling(text, ceiling=3) == "One two three four five six seven."
