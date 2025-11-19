"""SQLite storage helpers for persisting crawled records."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterable, Optional

from config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS crawled_records (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    publish_time TEXT,
    source_id TEXT,
    source_name TEXT,
    attachments TEXT,
    synced INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_crawled_records_url ON crawled_records(url);
"""


def initialize() -> None:
    """Ensure database file and schema exist."""
    path = Path(DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        _ensure_attachment_column(conn)


def _ensure_attachment_column(conn: sqlite3.Connection) -> None:
    """Add attachments column if the existing DB was created before it existed."""
    cursor = conn.execute("PRAGMA table_info(crawled_records)")
    columns = {row[1] for row in cursor.fetchall()}
    if "attachments" not in columns:
        conn.execute("ALTER TABLE crawled_records ADD COLUMN attachments TEXT")
        conn.commit()


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DATABASE_PATH)
    try:
        yield conn
    finally:
        conn.close()


def record_exists(record_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("SELECT 1 FROM crawled_records WHERE id=?", (record_id,))
        return cursor.fetchone() is not None


def insert_record(
    record_id: str,
    title: str,
    url: str,
    publish_time: Optional[str],
    source_id: str,
    source_name: str,
    synced: bool,
    attachments: Optional[str] = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO crawled_records
            (id, title, url, publish_time, source_id, source_name, attachments, synced)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                title,
                url,
                publish_time,
                source_id,
                source_name,
                attachments,
                int(synced),
            ),
        )
        conn.commit()


def mark_synced(record_ids: Iterable[str]) -> None:
    record_list = list(record_ids)
    if not record_list:
        return
    with get_connection() as conn:
        conn.executemany(
            "UPDATE crawled_records SET synced=1 WHERE id=?",
            ((record_id,) for record_id in record_list),
        )
        conn.commit()
