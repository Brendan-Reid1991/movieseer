"""SQLite persistence for the Movieseer event log.

EventStore is the single owner of all database I/O. No other module reads
from or writes to the database directly.

Each public method opens and closes its own aiosqlite connection so there is
no shared connection state to manage across the background collector and
concurrent SSE route reads.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import aiosqlite

from movieseer.event_log.types import EventSource, LogEvent

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT    NOT NULL,
    event_type TEXT    NOT NULL,
    title      TEXT    NOT NULL DEFAULT '',
    detail     TEXT    NOT NULL DEFAULT '',
    at         TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS watermarks (
    source  TEXT PRIMARY KEY,
    last_id INTEGER,
    last_at TEXT
);
"""


class EventStore:
    """Owns all SQLite reads and writes for the event log."""

    def __init__(self, db_path: str) -> None:
        self._path = db_path

    async def initialise(self) -> None:
        """Create tables if they do not exist."""
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    async def insert(self, events: list[LogEvent]) -> list[LogEvent]:
        """Persist a list of events atomically.

        Returns the same events with ``id`` populated from the database.
        A no-op (returns empty list) if ``events`` is empty.
        """
        if not events:
            return []

        now = datetime.now(UTC).isoformat()
        populated: list[LogEvent] = []

        async with aiosqlite.connect(self._path) as db:
            for event in events:
                cursor = await db.execute(
                    """
                    INSERT INTO events
                    (source, event_type, title, detail, at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["source"],
                        event["event_type"],
                        event["title"],
                        event["detail"],
                        event["at"],
                        now,
                    ),
                )
                populated.append({**event, "id": cursor.lastrowid})  # type: ignore[misc]
            await db.commit()

        return populated

    async def get_watermark(self, source: EventSource) -> tuple[int | None, str | None]:
        """Return ``(last_id, last_at)`` for a source, or ``(None, None)`` if unset."""
        async with aiosqlite.connect(self._path) as db:
            async with db.execute(
                "SELECT last_id, last_at FROM watermarks WHERE source = ?", (source,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None, None
        return row[0], row[1]

    async def set_watermark(
        self,
        source: EventSource,
        last_id: int | None,
        last_at: str | None,
    ) -> None:
        """Upsert the watermark for a source."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO watermarks (source, last_id, last_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET last_id = excluded.last_id,
                                                  last_at  = excluded.last_at
                """,
                (source, last_id, last_at),
            )
            await db.commit()

    async def recent(self, limit: int = 25) -> list[LogEvent]:
        """Return the most recent events, newest first."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, source, event_type, title, detail, at
                FROM events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()

        return [
            LogEvent(
                id=row["id"],
                source=row["source"],
                event_type=row["event_type"],
                title=row["title"],
                detail=row["detail"],
                at=row["at"],
            )
            for row in rows
        ]

    async def prune(self, retention_days: int) -> int:
        """Delete events older than ``retention_days``. Returns count deleted."""
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute("DELETE FROM events WHERE created_at < ?", (cutoff,))
            await db.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.debug("Pruned %d event(s) older than %d days", deleted, retention_days)
        return deleted
