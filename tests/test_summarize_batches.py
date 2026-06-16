"""_batches — map-reduce input packing (paragraph → sentence → hard-cut)."""
from readback.pipeline.summarize import _batches


def test_short_text_is_one_batch():
    text = "A short paragraph that easily fits."
    assert _batches(text, 1000) == [text]


def test_empty_and_whitespace_yield_no_batches():
    assert _batches("", 1000) == []
    assert _batches("   \n\n  \n\t", 1000) == []


def test_batches_respect_max_chars():
    paras = [f"Paragraph number {i} with a little body text here." for i in range(50)]
    text = "\n\n".join(paras)
    batches = _batches(text, 200)
    assert len(batches) > 1
    assert all(len(b) <= 200 for b in batches)
    # Every paragraph survives somewhere in the packed output.
    joined = " ".join(batches)
    for i in range(50):
        assert f"Paragraph number {i} " in joined


def test_packs_multiple_paragraphs_per_batch():
    # Three tiny paragraphs should pack into a single batch under a generous cap.
    text = "First para.\n\nSecond para.\n\nThird para."
    assert _batches(text, 1000) == [text]


def test_oversize_paragraph_falls_back_to_sentences():
    # One paragraph longer than max, made of clean sentences → split on sentences,
    # each batch within the cap.
    para = " ".join(f"This is sentence number {i}." for i in range(40))
    batches = _batches(para, 120)
    assert len(batches) > 1
    assert all(len(b) <= 120 for b in batches)


def test_giant_single_sentence_is_hard_cut():
    # A single sentence with no boundaries longer than max must still be split.
    giant = "word " * 200  # ~1000 chars, no sentence terminator
    batches = _batches(giant.strip(), 100)
    assert len(batches) > 1
    assert all(len(b) <= 100 for b in batches)
