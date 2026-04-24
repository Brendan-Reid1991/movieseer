"""Event collector — polls downstream services and writes new events to EventStore.

Responsibilities:
- One poll cycle per interval: fetch new history from each service since its watermark
- Diff Prowlarr indexer state to detect failures and recoveries
- Write signal events to EventStore; discard noise
- Prune stale events at the end of each cycle

This module has no knowledge of HTTP routing or SSE delivery. It returns new
events from ``poll_once()`` and lets the caller (main.py lifespan) broadcast them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from movieseer.aggregator.services.prowlarr import ProwlarrClient
from movieseer.aggregator.services.radarr import RadarrClient
from movieseer.aggregator.services.sabnzbd import SABnzbdClient
from movieseer.aggregator.services.sonarr import SonarrClient
from movieseer.config import SABNZBD_API_KEY
from movieseer.event_log.db import EventStore
from movieseer.event_log.types import EventType, LogEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signal allowlist — event types worth storing per source
# ---------------------------------------------------------------------------

_RADARR_SIGNALS: frozenset[str] = frozenset(
    {"grabbed", "downloadFailed", "downloadFolderImported", "movieFolderImported"}
)
_SONARR_SIGNALS: frozenset[str] = frozenset(
    {"grabbed", "downloadFailed", "downloadFolderImported"}
)

_ARR_EVENT_MAP: dict[str, EventType] = {
    "grabbed": "grabbed",
    "downloadFailed": "failed",
    "downloadFolderImported": "imported",
    "movieFolderImported": "imported",
}


def _is_signal_radarr(event_type: str) -> bool:
    return event_type in _RADARR_SIGNALS


def _is_signal_sonarr(event_type: str) -> bool:
    return event_type in _SONARR_SIGNALS


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class EventCollector:
    """Polls all configured services and writes signal events to EventStore."""

    def __init__(
        self,
        store: EventStore,
        radarr: RadarrClient,
        sonarr: SonarrClient,
        sabnzbd: SABnzbdClient,
        prowlarr: ProwlarrClient,
    ) -> None:
        self._store = store
        self._radarr = radarr
        self._sonarr = sonarr
        self._sabnzbd = sabnzbd
        self._prowlarr = prowlarr
        # In-memory set of currently-known failing indexer IDs for state diffing
        self._failing_indexers: set[int] = set()
        self._prowlarr_initialised = False

    async def run_forever(
        self,
        interval: int,
        broadcast_fn: Callable[[list[LogEvent]], None],
        retention_days: int,
    ) -> None:
        """Poll indefinitely, broadcasting new events after each cycle.

        Parameters
        ----------
        interval:
            Seconds to sleep between cycles.
        broadcast_fn:
            Called with the list of new LogEvents after each successful cycle.
            Plain (non-async) function — it puts events onto asyncio Queues.
        retention_days:
            Passed to ``EventStore.prune()`` after each cycle.
        """
        while True:
            try:
                new_events = await self.poll_once(retention_days)
                if new_events:
                    broadcast_fn(new_events)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unexpected error in collector poll cycle")
            await asyncio.sleep(interval)

    async def poll_once(self, retention_days: int = 7) -> list[LogEvent]:
        """Run one full poll cycle across all sources.

        Each source is polled concurrently. Per-source failures are caught and
        logged so one broken service never silences the others.

        Returns the list of newly inserted LogEvents (with ids set).
        """
        results = await asyncio.gather(
            self._poll_radarr(),
            self._poll_sonarr(),
            self._poll_sabnzbd(),
            self._poll_prowlarr(),
            return_exceptions=True,
        )

        new_events: list[LogEvent] = []
        source_names = ("radarr", "sonarr", "sabnzbd", "prowlarr")
        for name, result in zip(source_names, results, strict=True):
            if isinstance(result, Exception):
                logger.warning("Event collection failed for %s: %s", name, result)
            else:
                new_events.extend(result)

        inserted = await self._store.insert(new_events)
        await self._store.prune(retention_days)
        return inserted

    # ── per-source pollers ────────────────────────────────────────────────────

    async def _poll_radarr(self) -> list[LogEvent]:
        last_id, _ = await self._store.get_watermark("radarr")
        history = await self._radarr.history(page_length=50)

        new_events: list[LogEvent] = []
        max_id = last_id or 0

        for record in history:
            if not _is_signal_radarr(record.event_type):
                continue
            if last_id is not None and record.id <= last_id:
                continue

            event_type = _ARR_EVENT_MAP.get(record.event_type, "grabbed")
            title = record.source_title or "Unknown"
            detail = _radarr_detail(record.event_type, title)

            new_events.append(
                LogEvent(
                    id=0,
                    source="radarr",
                    event_type=event_type,  # type: ignore[arg-type]
                    title=title,
                    detail=detail,
                    at=record.date.isoformat(),
                )
            )
            if record.id > max_id:
                max_id = record.id

        if max_id > (last_id or 0):
            await self._store.set_watermark("radarr", max_id, None)

        return new_events

    async def _poll_sonarr(self) -> list[LogEvent]:
        last_id, _ = await self._store.get_watermark("sonarr")
        history = await self._sonarr.history(page_length=50)

        new_events: list[LogEvent] = []
        max_id = last_id or 0

        for record in history:
            if not _is_signal_sonarr(record.event_type):
                continue
            if last_id is not None and record.id <= last_id:
                continue

            event_type = _ARR_EVENT_MAP.get(record.event_type, "grabbed")
            title = record.source_title or "Unknown"
            detail = _sonarr_detail(record.event_type, title)

            new_events.append(
                LogEvent(
                    id=0,
                    source="sonarr",
                    event_type=event_type,  # type: ignore[arg-type]
                    title=title,
                    detail=detail,
                    at=record.date.isoformat(),
                )
            )
            if record.id > max_id:
                max_id = record.id

        if max_id > (last_id or 0):
            await self._store.set_watermark("sonarr", max_id, None)

        return new_events

    async def _poll_sabnzbd(self) -> list[LogEvent]:
        _, last_at = await self._store.get_watermark("sabnzbd")
        data = await self._sabnzbd._get(
            "",
            params={
                "mode": "history",
                "limit": 50,
                "apikey": SABNZBD_API_KEY,
                "output": "json",
            },
        )
        slots = (data or {}).get("history", {}).get("slots", [])

        new_events: list[LogEvent] = []
        max_completed: float = datetime.fromisoformat(last_at).timestamp() if last_at else 0.0

        for slot in slots:
            completed_ts: float = slot.get("completed", 0)
            if completed_ts <= max_completed:
                continue

            status: str = slot.get("status", "")
            if status not in ("Completed", "Failed"):
                continue

            name: str = slot.get("name", "Unknown")
            fail_msg: str = slot.get("fail_message", "")
            completed_dt = datetime.fromtimestamp(completed_ts, tz=UTC).isoformat()

            if status == "Completed":
                event_type: EventType = "completed"
                detail = f"Completed {name}"
            else:
                event_type = "failed"
                detail = f"Failed {name}" + (f" — {fail_msg}" if fail_msg else "")

            new_events.append(
                LogEvent(
                    id=0,
                    source="sabnzbd",
                    event_type=event_type,
                    title=name,
                    detail=detail,
                    at=completed_dt,
                )
            )
            if completed_ts > max_completed:
                max_completed = completed_ts

        if max_completed > 0 and (
            not last_at or max_completed > datetime.fromisoformat(last_at).timestamp()
        ):
            await self._store.set_watermark(
                "sabnzbd",
                None,
                datetime.fromtimestamp(max_completed, tz=UTC).isoformat(),
            )

        return new_events

    async def _poll_prowlarr(self) -> list[LogEvent]:
        indexers = await self._prowlarr.indexers()
        current_failing: set[int] = {i["id"] for i in indexers if i.get("failing")}

        new_events: list[LogEvent] = []
        now = datetime.now(UTC).isoformat()

        if not self._prowlarr_initialised:
            # First run — record current state without emitting events
            self._failing_indexers = current_failing
            self._prowlarr_initialised = True
            return []

        id_to_name = {i["id"]: i["name"] for i in indexers}

        # Newly failing
        for idx_id in current_failing - self._failing_indexers:
            name = id_to_name.get(idx_id, str(idx_id))
            error = next((i.get("error") or "" for i in indexers if i["id"] == idx_id), "")
            new_events.append(
                LogEvent(
                    id=0,
                    source="prowlarr",
                    event_type="indexer_failing",
                    title=name,
                    detail=f"{name} is failing" + (f" — {error}" if error else ""),
                    at=now,
                )
            )

        # Recovered
        for idx_id in self._failing_indexers - current_failing:
            name = id_to_name.get(idx_id, str(idx_id))
            new_events.append(
                LogEvent(
                    id=0,
                    source="prowlarr",
                    event_type="indexer_recovered",
                    title=name,
                    detail=f"{name} recovered",
                    at=now,
                )
            )

        self._failing_indexers = current_failing
        return new_events


# ---------------------------------------------------------------------------
# Detail formatters — plain functions, no I/O
# ---------------------------------------------------------------------------


def _radarr_detail(event_type: str, title: str) -> str:
    if event_type == "grabbed":
        return f"Grabbed {title}"
    if event_type in ("downloadFolderImported", "movieFolderImported"):
        return f"Imported {title}"
    if event_type == "downloadFailed":
        return f"Failed — {title}"
    return title


def _sonarr_detail(event_type: str, title: str) -> str:
    if event_type == "grabbed":
        return f"Grabbed {title}"
    if event_type == "downloadFolderImported":
        return f"Imported {title}"
    if event_type == "downloadFailed":
        return f"Failed — {title}"
    return title
