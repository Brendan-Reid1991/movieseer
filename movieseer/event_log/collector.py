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
from typing import Literal

from movieseer.services import ProwlarrClient, RadarrClient, SABnzbdClient, SonarrClient
from movieseer.services.data_structures.prowlarr_models import ProwlarrIndexer
from movieseer.services.data_structures.sabnzbd_models import HistorySlot

from .db import EventStore
from .types import EVENT_MAP, ArrHistoryEvent, LogEvent, SabnzbdSlotStatus

logger = logging.getLogger(__name__)


class EventCollector:
    """Polls all downstream services and writes signal events to EventStore.

    Radarr, Sonarr, and SABnzbd all expose history endpoints; Prowlarr does not.
    History-based sources use a per-source watermark stored in EventStore to avoid
    re-processing records already seen. Prowlarr requires in-memory state diffing
    instead — there is no persistent log of indexer health transitions, so we
    compare each new snapshot against the previous one.

    Parameters
    ----------
    store : EventStore
        Persistent storage for events and per-source watermarks.
    radarr : RadarrClient
        Client for the Radarr movie download manager.
    sonarr : SonarrClient
        Client for the Sonarr TV download manager.
    sabnzbd : SABnzbdClient
        Client for the SABnzbd download client.
    prowlarr : ProwlarrClient
        Client for the Prowlarr indexer manager.
    """

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
        """Poll all sources indefinitely, broadcasting new events after each cycle.

        Exceptions from individual cycles are caught and logged rather than re-raised
        because a transient upstream error should stall one cycle, not kill the
        background task. ``asyncio.CancelledError`` is re-raised immediately so the
        task responds correctly to application shutdown.

        Parameters
        ----------
        interval : int
            Seconds to sleep between poll cycles.
        broadcast_fn : Callable[[list[LogEvent]], None]
            Called with newly inserted events after each successful cycle. Must be a
            plain (non-async) function — it enqueues events onto asyncio Queues without
            awaiting anything itself.
        retention_days : int
            Passed to ``EventStore.prune()`` at the end of each cycle.
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
        """Run one complete poll cycle and return newly inserted events.

        Sources are polled concurrently via ``asyncio.gather`` with
        ``return_exceptions=True`` so that a single broken service never blocks or
        suppresses output from the healthy ones. Per-source failures are logged at
        WARNING level; the cycle still returns whatever the healthy sources produced.

        Parameters
        ----------
        retention_days : int, optional
            Events older than this many days are pruned at the end of the cycle.

        Returns
        -------
        list[LogEvent]
            Newly inserted events with their database-assigned ``id`` set.
            Empty if no new events were found.
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
                logger.warning(
                    f"Event collection failed for {name}. "
                    f"Exception class {type(result)}, message: {str(result)}"
                )
            else:
                new_events.extend(result)

        inserted = await self._store.insert(new_events)
        await self._store.prune(retention_days)
        return inserted

    # ── per-source pollers ────────────────────────────────────────────────────

    async def _poll_radarr_sonarr(self, service: Literal["sonarr", "radarr"]) -> list[LogEvent]:
        """Fetch new history from Radarr or Sonarr and return signal events.

        Both services expose identical history API shapes, so a single implementation
        handles both. The watermark is the highest record ID seen so far; integer IDs
        are safe here because both services guarantee their history IDs are stable and
        monotonically increasing.

        Records whose ``event_type`` is absent from ``EVENT_MAP`` are noise
        (e.g. ``seriesAdded``, ``fileRenamed``) and are silently skipped.

        Parameters
        ----------
        service : {"radarr", "sonarr"}
            Selects the client to call and the watermark key to read/write.

        Returns
        -------
        list[LogEvent]
            New signal events since the last watermark. Empty if nothing new.
        """
        match service:
            case "sonarr":
                client = self._sonarr
            case "radarr":
                client = self._radarr
            case _:
                raise ValueError(f"Unrecognised client: {service}.")

        last_id, _ = await self._store.get_watermark(service)
        history = await client.history()

        new_events: list[LogEvent] = []
        max_id = last_id or 0

        for record in history:
            if record.event_type not in EVENT_MAP:
                logger.debug(
                    "%s poll: skipping event %s as it is not in EventMap",
                    service,
                    record.event_type,
                )
                continue
            if last_id is not None and record.id <= last_id:
                logger.debug(
                    "%s poll: skipping event %s with ID %s. Watermark ID is %s.",
                    service,
                    record.event_type,
                    record.id,
                    last_id,
                )
                continue
            title = record.source_title or "Unknown"
            new_events.append(
                LogEvent(
                    id=0,
                    source=service,
                    event_type=EVENT_MAP[record.event_type],  # type: ignore[arg-type]
                    title=title,
                    detail=_radarr_sonarr_detail(record.event_type, title),
                    at=record.date.isoformat(),
                )
            )
            if record.id > max_id:
                max_id = record.id

        if max_id > (last_id or 0):
            await self._store.set_watermark(service, max_id, None)

        return new_events

    async def _poll_radarr(self) -> list[LogEvent]:
        return await self._poll_radarr_sonarr("radarr")

    async def _poll_sonarr(self) -> list[LogEvent]:
        return await self._poll_radarr_sonarr("sonarr")

    async def _poll_sabnzbd(self) -> list[LogEvent]:
        """Fetch completed SABnzbd slots and return new signal events.

        SABnzbd history slots do not have stable ascending IDs, so the ``completed``
        Unix timestamp is used as the watermark cursor instead. Only ``Completed`` and
        ``Failed`` terminal states are recorded — intermediate states such as
        ``Downloading`` and ``Verifying`` are not signals worth storing.

        Returns
        -------
        list[LogEvent]
            New ``completed`` or ``failed`` events since the last watermark.
            Empty if no slots have finished since the previous cycle.
        """
        _, last_at = await self._store.get_watermark("sabnzbd")
        slots: dict[str, HistorySlot] = await self._sabnzbd.slots_history()

        new_events: list[LogEvent] = []
        max_completed: float = datetime.fromisoformat(last_at).timestamp() if last_at else 0.0
        initial_max = max_completed

        for slot in slots.values():
            if slot.completed <= max_completed:
                logger.debug(
                    "Skipping completed slot %s. Watermark is %s", slot.name, max_completed
                )
                continue

            if slot.status not in SabnzbdSlotStatus:
                logger.debug("Skipping completed slot %s. Status is %s", slot.name, slot.status)
                continue

            match slot.status:
                case SabnzbdSlotStatus.COMPLETED:
                    new_events.append(
                        LogEvent(
                            id=0,
                            source="sabnzbd",
                            event_type="completed",
                            title=slot.name,
                            detail=f"Completed {slot.name}",
                            at=slot.completed_as_iso,
                        )
                    )
                case SabnzbdSlotStatus.FAILED:
                    new_events.append(
                        LogEvent(
                            id=0,
                            source="sabnzbd",
                            event_type="failed",
                            title=slot.name,
                            detail=f"Failed {slot.name}: "
                            f"{slot.fail_message or 'No failure message'}",
                            at=slot.completed_as_iso,
                        )
                    )

            if slot.completed > max_completed:
                max_completed = slot.completed

        if max_completed > initial_max:
            await self._store.set_watermark(
                "sabnzbd",
                None,
                datetime.fromtimestamp(max_completed, tz=UTC).isoformat(),
            )

        return new_events

    async def _poll_prowlarr(self) -> list[LogEvent]:
        """Diff current Prowlarr indexer state against the previous snapshot.

        Prowlarr exposes only the current state of each indexer — there is no event
        log for health transitions. We maintain ``_failing_indexers`` in memory and
        compare successive snapshots to emit events only when an indexer transitions
        between healthy and failing.

        On the first call we record the current state as the baseline and return
        immediately without emitting events. We have no prior snapshot to diff against,
        so emitting on startup would produce spurious alerts for pre-existing failures
        the user has already seen.

        Returns
        -------
        list[LogEvent]
            ``indexer_failing`` events for newly failed indexers and
            ``indexer_recovered`` events for newly healthy ones.
            Returns an empty list on the first call (baseline capture only).
        """
        indexers = await self._prowlarr.indexers()
        current_failing: set[int] = {i.id for i in indexers if i.failing}

        new_events: list[LogEvent] = []
        now = datetime.now(UTC).isoformat()

        if not self._prowlarr_initialised:
            # First run — record current state without emitting events
            self._failing_indexers = current_failing
            self._prowlarr_initialised = True
            return []

        indexers_by_id: dict[int, ProwlarrIndexer] = {i.id: i for i in indexers}

        # Newly failing
        for indexer_id in current_failing - self._failing_indexers:
            indexer = indexers_by_id[indexer_id]
            new_events.append(
                LogEvent(
                    id=0,
                    source="prowlarr",
                    event_type="indexer_failing",
                    title=indexer.name,
                    detail=f"{indexer.name} is failing: "
                    f"{indexer.error or 'No failure reason found.'}",
                    at=now,
                )
            )

        # Recovered
        for indexer_id in self._failing_indexers - current_failing:
            indexer = indexers_by_id[indexer_id]
            new_events.append(
                LogEvent(
                    id=0,
                    source="prowlarr",
                    event_type="indexer_recovered",
                    title=indexer.name,
                    detail=f"{indexer.name} recovered",
                    at=now,
                )
            )

        self._failing_indexers = current_failing
        return new_events


def _radarr_sonarr_detail(event_type: ArrHistoryEvent, title: str) -> str:
    """Format a human-readable detail string for a Radarr/Sonarr history event.

    The wildcard arm raises rather than returning a fallback so that adding a new
    ``ArrHistoryEvent`` variant without updating this function fails loudly at runtime
    instead of silently producing a misleading message.

    Parameters
    ----------
    event_type : ArrHistoryEvent
        The history event type to format.
    title : str
        The media title associated with the event.

    Returns
    -------
    str
        Human-readable description suitable for display in the event log.
    """
    match event_type:
        case ArrHistoryEvent.GRABBED:
            return f"Grabbed {title}"
        case ArrHistoryEvent.DOWNLOAD_FOLDER_IMPORTED | ArrHistoryEvent.MOVIE_FOLDER_IMPORTED:
            return f"Imported {title}"
        case ArrHistoryEvent.DOWNLOAD_FAILED:
            return f"Failed — {title}"
        case _:
            raise ValueError(f"Unrecognised event type: {event_type}")
