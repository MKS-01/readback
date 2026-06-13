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
                    created_at     TEXT NOT NULL
                )
                """
            )
            # Sort key — every list query orders by it.
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reads_created ON reads(created_at)")

    def add(self, rec: ReadRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reads
                    (id, title, summary, excerpt, source_url, mode, voice,
                     duration_sec, word_count, audio_filename, audio_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.id, rec.title, rec.summary, rec.excerpt, rec.source_url,
                    rec.mode, rec.voice, rec.duration_sec, rec.word_count,
                    rec.audio_filename, rec.audio_path, rec.created_at,
                ),
            )

    def list(self, q: str = "", sort: Literal["newest", "oldest"] = "newest") -> list[dict]:
        order = _SORTS.get(sort, "DESC")
        sql = f"SELECT {_CARD_COLS} FROM reads"
        params: tuple = ()
        if q:
            like = f"%{q}%"
            sql += (
                " WHERE title LIKE ? OR summary LIKE ? OR excerpt LIKE ? "
                "OR source_url LIKE ?"
            )
            params = (like, like, like, like)
        sql += f" ORDER BY created_at {order}"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

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
