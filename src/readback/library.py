"""Read library — SQLite persistence for synthesized reads.

Every finished read writes a WAV to `cfg.reader.output_dir` and a metadata row
here, so the dashboard can list / search / replay past reads. Stdlib `sqlite3`
only (no ORM, no extra dependency): one file, one `reads` table, near-zero RAM —
Pi-friendly.

The audio itself stays on disk in the reader output dir; this DB only records
*where* it is (`audio_path`, absolute) plus the card metadata. Connections are
opened per call so the class is safe to use from asyncio's threadpool (every
call site wraps these in `asyncio.to_thread`).
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

log = logging.getLogger("readback.library")

_SORTS = {"newest": "DESC", "oldest": "ASC"}

# Columns returned for the card list (cheap) vs. full detail (adds nothing extra
# here — the table is small — but kept explicit so the API shape is obvious).
_CARD_COLS = (
    "id, title, summary, excerpt, source_url, mode, voice, "
    "duration_sec, word_count, audio_filename, created_at"
)


@dataclass
class ReadRecord:
    """One synthesized read. `id` is the WAV's uuid stem (also its filename
    without `.wav`). `summary` is the spoken summary in Summary mode, None in
    Full mode; `excerpt` is always present so Full reads still preview."""
    id: str
    title: str
    source_url: str
    mode: str
    voice: str
    duration_sec: float
    word_count: int
    audio_filename: str
    audio_path: str
    created_at: str
    excerpt: str = ""
    summary: Optional[str] = None
    llm_model: str = ""
    # Pipeline recipe that produced the audio — see pipeline.RECIPE_VERSION.
    recipe: str = ""


class Library:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reads (
                    id             TEXT PRIMARY KEY,
                    title          TEXT NOT NULL,
                    summary        TEXT,
                    excerpt        TEXT NOT NULL DEFAULT '',
                    source_url     TEXT NOT NULL,
                    mode           TEXT NOT NULL,
                    voice          TEXT NOT NULL,
                    duration_sec   REAL NOT NULL,
                    word_count     INTEGER NOT NULL,
                    audio_filename TEXT NOT NULL,
                    audio_path     TEXT NOT NULL,
                    created_at     TEXT NOT NULL,
                    llm_model      TEXT NOT NULL DEFAULT '',
                    recipe         TEXT NOT NULL DEFAULT ''
                )
                """
            )
            # Migration: add llm_model to existing DBs (must run before indexes
            # that reference it).
            for column in ("llm_model", "recipe"):
                try:
                    conn.execute(
                        f"ALTER TABLE reads ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                    )
                except sqlite3.OperationalError:
                    pass        # already present
            # Sort key — every list query orders by it.
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reads_created ON reads(created_at)")
            # Cache lookup index — covers find_cached's full key.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reads_cache "
                "ON reads(source_url, mode, voice, llm_model, recipe)"
            )

    def add(self, rec: ReadRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reads
                    (id, title, summary, excerpt, source_url, mode, voice,
                     duration_sec, word_count, audio_filename, audio_path,
                     created_at, llm_model, recipe)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.id, rec.title, rec.summary, rec.excerpt, rec.source_url,
                    rec.mode, rec.voice, rec.duration_sec, rec.word_count,
                    rec.audio_filename, rec.audio_path, rec.created_at,
                    rec.llm_model, rec.recipe,
                ),
            )

    def find_cached(
        self, source_url: str, mode: str, voice: str, llm_model: str,
        recipe: str = "",
    ) -> Optional[dict]:
        """Return the most recent read matching the cache key, or None. Only
        returns a hit if the WAV file still exists on disk.

        ⚠ `recipe` (pipeline.RECIPE_VERSION) is part of the key so a pipeline
        change re-renders instead of replaying audio the OLD code produced."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reads "
                "WHERE source_url = ? AND mode = ? AND voice = ? AND llm_model = ? "
                "AND recipe = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (source_url, mode, voice, llm_model, recipe),
            ).fetchone()
        if row is None:
            return None
        rec = dict(row)
        if not Path(rec["audio_path"]).exists():
            return None
        return rec

    @staticmethod
    def _where(q: str) -> tuple[str, tuple]:
        """Shared search filter for list() + count() so they always agree."""
        if not q:
            return "", ()
        like = f"%{q}%"
        clause = (
            " WHERE title LIKE ? OR summary LIKE ? OR excerpt LIKE ? "
            "OR source_url LIKE ?"
        )
        return clause, (like, like, like, like)

    def list(
        self,
        q: str = "",
        sort: Literal["newest", "oldest"] = "newest",
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[dict]:
        order = _SORTS.get(sort, "DESC")
        where, params = self._where(q)
        sql = f"SELECT {_CARD_COLS} FROM reads{where} ORDER BY created_at {order}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = params + (limit, max(0, offset))
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def count(self, q: str = "") -> int:
        """Total rows matching `q` (for pagination — independent of limit/offset)."""
        where, params = self._where(q)
        with self._connect() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM reads{where}", params).fetchone()[0])

    def get(self, read_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM reads WHERE id = ?", (read_id,)).fetchone()
            return dict(row) if row else None

    def delete(self, read_id: str) -> Optional[str]:
        """Delete the row; return its `audio_path` (so the caller can unlink the
        WAV) or None if the id was unknown."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT audio_path FROM reads WHERE id = ?", (read_id,)
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM reads WHERE id = ?", (read_id,))
            return row["audio_path"]
