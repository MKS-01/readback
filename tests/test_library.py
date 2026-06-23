"""Library — SQLite CRUD, search, pagination, delete."""
import pytest

from readback.library import Library, ReadRecord


def _rec(id_, title="Title", *, summary=None, excerpt="", url="https://x",
         created="2026-01-01", mode="full", voice="kay", llm_model=""):
    return ReadRecord(
        id=id_, title=title, source_url=url, mode=mode, voice=voice,
        duration_sec=1.0, word_count=10, audio_filename=f"{id_}.wav",
        audio_path=f"/audio/{id_}.wav", created_at=created, excerpt=excerpt,
        summary=summary, llm_model=llm_model,
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


# ── Cache lookup ─────────────────────────────────────────────────────

def test_find_cached_returns_latest_match(lib, tmp_path):
    wav = tmp_path / "b.wav"
    wav.write_bytes(b"RIFF")
    lib.add(_rec("a", url="https://ex.com", llm_model="m1",
                 created="2026-01-01"))
    lib.add(_rec("b", url="https://ex.com", llm_model="m1",
                 created="2026-06-01"))
    # Patch audio_path so the file-exists check passes.
    with lib._connect() as conn:
        conn.execute("UPDATE reads SET audio_path = ? WHERE id = 'b'", (str(wav),))
    hit = lib.find_cached("https://ex.com", "full", "kay", "m1")
    assert hit is not None
    assert hit["id"] == "b"


def test_find_cached_miss_on_different_voice(lib, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    lib.add(_rec("a", url="https://ex.com", llm_model="m1"))
    with lib._connect() as conn:
        conn.execute("UPDATE reads SET audio_path = ? WHERE id = 'a'", (str(wav),))
    assert lib.find_cached("https://ex.com", "full", "other_voice", "m1") is None


def test_find_cached_miss_on_different_model(lib, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    lib.add(_rec("a", url="https://ex.com", llm_model="m1"))
    with lib._connect() as conn:
        conn.execute("UPDATE reads SET audio_path = ? WHERE id = 'a'", (str(wav),))
    assert lib.find_cached("https://ex.com", "full", "kay", "m2") is None


def test_find_cached_miss_when_wav_deleted(lib):
    lib.add(_rec("a", url="https://ex.com", llm_model="m1"))
    # audio_path points to a non-existent file
    assert lib.find_cached("https://ex.com", "full", "kay", "m1") is None


def test_llm_model_persisted(lib):
    lib.add(_rec("a", llm_model="mlx-community/Qwen3.5-9B-4bit"))
    row = lib.get("a")
    assert row["llm_model"] == "mlx-community/Qwen3.5-9B-4bit"
