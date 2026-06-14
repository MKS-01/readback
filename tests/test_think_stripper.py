"""_ThinkStripper / strip_think — remove <think>…</think>, even split across feeds."""
from readback.llm.client import _ThinkStripper, _safe_emit_len, strip_think


def test_removes_a_think_span():
    assert strip_think("Hello <think>secret reasoning</think>world") == "Hello world"


def test_text_without_think_is_unchanged():
    assert strip_think("just plain output") == "just plain output"


def test_multiple_think_spans():
    out = strip_think("a<think>x</think>b<think>y</think>c")
    assert out == "abc"


def test_unclosed_think_is_discarded_on_flush():
    s = _ThinkStripper()
    emitted = s.feed("keep <think>never ends...")
    assert s.flush() == ""           # the open think tail is dropped
    assert emitted == "keep "


def test_streaming_split_across_feeds():
    s = _ThinkStripper()
    out = ""
    # The "<think>" tag is split across feed boundaries — the stripper must hold
    # the ambiguous suffix until it can decide.
    for piece in ["before <th", "ink>hidden</thi", "nk>after"]:
        out += s.feed(piece)
    out += s.flush()
    assert out == "before after"


def test_safe_emit_len_holds_back_partial_needle():
    # "ab<th" — the trailing "<th" could become "<think>", so hold it back.
    assert _safe_emit_len("ab<th", ("<think>",)) == 2
    # No partial match — everything is safe to emit.
    assert _safe_emit_len("abc", ("<think>",)) == 3
