"""chunk_text — sentence-aware, paragraph-respecting TTS chunking."""
from readback.pipeline.speak import chunk_text, _MAX_CHARS


def test_short_text_is_a_single_chunk():
    assert chunk_text("") == []
    assert chunk_text("Hello world, this is readback.") == [
        "Hello world, this is readback."
    ]


def test_sentences_merge_up_to_max():
    sentences = ["This is sentence number {}.".format(i) for i in range(20)]
    chunks = chunk_text(" ".join(sentences))
    assert len(chunks) < len(sentences)
    assert all(len(c) <= _MAX_CHARS for c in chunks)


def test_paragraph_boundary_forces_a_split():
    a = "First paragraph has enough text to stand on its own here."
    b = "Second paragraph is also clearly long enough to be its own chunk."
    chunks = chunk_text(a + "\n" + b)
    assert chunks == [a, b]


def test_overlong_sentence_splits_on_commas():
    clause = "this clause repeats several times to exceed the cap"
    sentence = ", ".join([clause] * 8) + "."
    assert len(sentence) > _MAX_CHARS
    chunks = chunk_text(sentence)
    assert len(chunks) > 1


def test_short_fragment_is_never_dropped():
    # A sub-_MIN_CHARS sentence ("Wow!") followed by a sentence that may not fit
    # the drawn random cap must be carried forward, not silently discarded.
    sentence = "This deliberately padded sentence keeps going for long enough " \
               "that it can overflow whichever random cap the chunker drew here."
    for _ in range(100):
        chunks = chunk_text("Wow! " + sentence)
        assert "Wow!" in " ".join(chunks)


def test_comma_free_overlong_sentence_is_hard_split():
    sentence = "word" * 3 + " ".join(["antidisestablishmentarianism"] * 20) + "."
    assert len(sentence) > _MAX_CHARS and "," not in sentence
    chunks = chunk_text(sentence)
    assert all(len(c) <= _MAX_CHARS for c in chunks)
    assert len(chunks) > 1
