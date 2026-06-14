"""chunk_text — sentence-aware, paragraph-respecting TTS chunking."""
from readback.pipeline.speak import chunk_text, _MAX_CHARS, _MIN_CHARS


def test_empty_and_whitespace_yield_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n  \n\t") == []


def test_short_text_is_a_single_chunk():
    assert chunk_text("Hello world, this is readback.") == [
        "Hello world, this is readback."
    ]


def test_sentences_in_one_paragraph_merge_up_to_max():
    # Several short sentences in one paragraph collapse into fewer chunks.
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
    sentence = ", ".join([clause] * 8) + "."   # well over _MAX_CHARS, comma-separated
    assert len(sentence) > _MAX_CHARS
    chunks = chunk_text(sentence)
    assert len(chunks) > 1


def test_no_chunk_is_below_min_when_content_allows():
    chunks = chunk_text("A long, readable paragraph that easily clears the floor.")
    assert all(len(c) >= _MIN_CHARS for c in chunks)
