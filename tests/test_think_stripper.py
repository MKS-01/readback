"""_ThinkStripper / strip_think — remove <think>…</think>, even split across feeds."""
from readback.llm.client import _ThinkStripper, strip_think


def test_removes_a_think_span():
    assert strip_think("Hello <think>secret reasoning</think>world") == "Hello world"


def test_text_without_think_is_unchanged():
    assert strip_think("just plain output") == "just plain output"


def test_unclosed_think_is_discarded_on_flush():
    s = _ThinkStripper()
    emitted = s.feed("keep <think>never ends...")
    assert s.flush() == ""           # the open think tail is dropped
    assert emitted == "keep "


def test_streaming_split_across_feeds():
    s = _ThinkStripper()
    out = ""
    for piece in ["before <th", "ink>hidden</thi", "nk>after"]:
        out += s.feed(piece)
    out += s.flush()
    assert out == "before after"
