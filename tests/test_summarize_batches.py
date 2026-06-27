"""_batches — map-reduce input packing (paragraph → sentence → hard-cut)."""
from readback.pipeline.summarize import _batches


def test_short_text_is_one_batch():
    assert _batches("", 1000) == []
    assert _batches("A short paragraph that easily fits.", 1000) == [
        "A short paragraph that easily fits."
    ]


def test_batches_respect_max_chars():
    paras = [f"Paragraph number {i} with a little body text here." for i in range(50)]
    text = "\n\n".join(paras)
    batches = _batches(text, 200)
    assert len(batches) > 1
    assert all(len(b) <= 200 for b in batches)
    joined = " ".join(batches)
    for i in range(50):
        assert f"Paragraph number {i} " in joined


def test_oversize_paragraph_falls_back_to_sentences():
    para = " ".join(f"This is sentence number {i}." for i in range(40))
    batches = _batches(para, 120)
    assert len(batches) > 1
    assert all(len(b) <= 120 for b in batches)


def test_giant_single_sentence_is_hard_cut():
    giant = "word " * 200
    batches = _batches(giant.strip(), 100)
    assert len(batches) > 1
    assert all(len(b) <= 100 for b in batches)
