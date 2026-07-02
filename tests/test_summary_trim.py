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
