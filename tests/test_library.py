"""Library — SQLite CRUD, search, pagination, delete."""
import pytest

from readback.library import Library, ReadRecord


def _rec(id_, title="Title", *, summary=None, excerpt="", url="https://x", created="2026-01-01"):
    return ReadRecord(
        id=id_, title=title, source_url=url, mode="full", voice="kay",
        duration_sec=1.0, word_count=10, audio_filename=f"{id_}.wav",
        audio_path=f"/audio/{id_}.wav", created_at=created, excerpt=excerpt, summary=summary,
    )


@pytest.fixture
def lib(tmp_path):
    return Library(tmp_path / "library.db")


def test_add_then_get_roundtrip(lib):
    lib.add(_rec("a", "Hello", summary="spoken", excerpt="ex"))
    row = lib.get("a")
    assert row["id"] == "a"
    assert row["title"] == "Hello"
    assert row["summary"] == "spoken"
    assert lib.get("missing") is None


def test_list_sort_newest_and_oldest(lib):
    lib.add(_rec("old", created="2026-01-01"))
    lib.add(_rec("new", created="2026-06-01"))
    assert [r["id"] for r in lib.list(sort="newest")] == ["new", "old"]
    assert [r["id"] for r in lib.list(sort="oldest")] == ["old", "new"]


def test_search_matches_title_and_url(lib):
    lib.add(_rec("a", title="Kotlin Multiplatform"))
    lib.add(_rec("b", title="Something else", url="https://kotlinlang.org"))
    lib.add(_rec("c", title="Unrelated"))
    ids = {r["id"] for r in lib.list(q="kotlin")}
    assert ids == {"a", "b"}


def test_count_is_independent_of_pagination(lib):
    for i in range(5):
        lib.add(_rec(str(i), created=f"2026-01-0{i+1}"))
    assert lib.count() == 5
    page = lib.list(limit=2, offset=0)
    assert len(page) == 2
    assert lib.count() == 5  # unchanged by the limited query


def test_pagination_offset(lib):
    for i in range(5):
        lib.add(_rec(str(i), created=f"2026-01-0{i+1}"))
    first = [r["id"] for r in lib.list(sort="oldest", limit=2, offset=0)]
    second = [r["id"] for r in lib.list(sort="oldest", limit=2, offset=2)]
    assert first == ["0", "1"]
    assert second == ["2", "3"]


def test_insert_or_replace_overwrites_same_id(lib):
    lib.add(_rec("a", title="First"))
    lib.add(_rec("a", title="Second"))
    assert lib.count() == 1
    assert lib.get("a")["title"] == "Second"


def test_delete_returns_audio_path_and_removes_row(lib):
    lib.add(_rec("a"))
    assert lib.delete("a") == "/audio/a.wav"
    assert lib.get("a") is None
    assert lib.delete("a") is None  # second delete: unknown id
