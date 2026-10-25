from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from movieseer.config import HISTORY_WINDOW_DAYS
from movieseer.services.data_structures.arr_models import ArrHistoryEntry, ArrQueueEntry
from movieseer.services.data_structures.radarr_models import (
    Movie,
    RadarrHistoryEntry,
    RadarrQueueEntry,
)
from movieseer.services.data_structures.sonarr_models import (
    Series,
    SonarrHistoryEntry,
    SonarrQueueEntry,
)

from .types import (
    ArrStatus,
    HistoryEvent,
    RequestItem,
)

logger = logging.getLogger(__name__)


def movie_requests(
    ids: list[int],
    details: list[Movie | BaseException],
    queue: list[RadarrQueueEntry],
    hist: list[RadarrHistoryEntry],
) -> list[RequestItem]:
    """Assemble RequestItems from the three async Radarr data sources.

    ``details`` is produced by ``asyncio.gather(*[radarr.movie(mid) for mid in ids],
    return_exceptions=True)``. Individual lookup failures surface as ``BaseException``
    instances rather than propagating — that is why we check with ``isinstance`` before
    using each result. ``zip(..., strict=True)`` enforces that the id list and results
    list have not been accidentally misaligned by the caller.

    Parameters
    ----------
    ids : list[int]
        Radarr movie IDs, in the same order as ``details``.
    details : list[Movie | BaseException]
        Per-movie lookup results from a ``return_exceptions=True`` gather. Failed
        lookups arrive as exceptions and are logged then skipped.
    queue : list[RadarrQueue]
        All active Radarr queue entries; filtered per movie inside this function.
    hist : list[RadarrHistory]
        All recent Radarr history events; filtered per movie inside this function.

    Returns
    -------
    list[RequestItem]
        One item per successfully fetched movie; failed lookups are excluded.
    """
    results = []
    for movie_id, movie in zip(ids, details, strict=True):
        if isinstance(movie, BaseException):
            logger.warning("Radarr movie lookup failed for id %s: %s", movie_id, movie)
            continue
        results.append(
            build_request_from_radarr(
                movie,
                next((q for q in queue if q.movie_id == movie_id), None),
                [e for e in hist if e.movie_id == movie_id],
            )
        )
    return results


def series_requests(
    ids: list[int],
    details: list[Series | BaseException],
    queue: list[SonarrQueueEntry],
    hist: list[SonarrHistoryEntry],
) -> list[RequestItem]:
    """Assemble RequestItems from the three async Sonarr data sources.

    Mirrors ``movie_requests``: ``details`` comes from a ``return_exceptions=True``
    gather, so a failed per-series lookup arrives as a ``BaseException`` and is
    logged and skipped rather than aborting the rest of the batch.

    Parameters
    ----------
    ids : list[int]
        Sonarr series IDs, in the same order as ``details``.
    details : list[Series | BaseException]
        Per-series lookup results from a ``return_exceptions=True`` gather. Failed
        lookups arrive as exceptions and are logged then skipped.
    queue : list[SonarrQueue]
        All active Sonarr queue entries; filtered per series inside this function.
    hist : list[SonarrHistory]
        All recent Sonarr history events; filtered per series inside this function.

    Returns
    -------
    list[RequestItem]
        One item per successfully fetched series; failed lookups are excluded.
    """
    results = []
    for series_id, series in zip(ids, details, strict=True):
        if isinstance(series, BaseException):
            logger.warning("Sonarr series lookup failed for id %s: %s", series_id, series)
            continue
        results.append(
            build_request_from_sonarr(
                series,
                [q for q in queue if q.series_id == series_id],
                [e for e in hist if e.series_id == series_id],
            )
        )
    return results


def build_request_from_radarr(
    media: Movie,
    queue_item: RadarrQueueEntry | None,
    hist_events: list[RadarrHistoryEntry],
) -> RequestItem:
    """Build a RequestItem for a movie sourced directly from Radarr.

    ``id`` is ``None`` and ``requested_by`` is hardcoded to "Radarr" because items
    added directly in Radarr have no Seerr request ID or named requester.
    Status priority: active queue entry > file already on disk > history fallback.
    History is capped at five events; deeper history is noise at the UI level.
    ``requested_at`` is derived from the first history event because direct Radarr
    additions carry no dedicated "requested" timestamp.

    Parameters
    ----------
    media : Movie
        The Radarr movie object, used for title and ``has_file`` flag.
    queue_item : RadarrQueue or None
        The active download queue entry for this movie, if one exists.
    hist_events : list[RadarrHistory]
        History events for this movie, newest first.

    Returns
    -------
    RequestItem
        Status snapshot for the movie, with ``source`` set to ``"radarr"``.
    """
    item: RequestItem = {
        "id": None,
        "title": media.title,
        "type": "movie",
        "source": "radarr",
        "requested_by": "Radarr",
        "requested_at": None,
        "seerr_status": None,
        "arr": None,
        "history": [],
    }
    if queue_item:
        item["arr"] = arr_queue_status(queue_item)
    elif media.has_file:
        item["arr"] = {"status": "imported", "error": None}
        item["history"] = format_history(hist_events[:5])
        item["requested_at"] = hist_events[0].date.isoformat() if hist_events else None
    else:
        item["arr"] = arr_history_status(hist_events)
        item["history"] = format_history(hist_events[:5])
    return item


def build_request_from_sonarr(
    media: Series,
    queue_items: list[SonarrQueueEntry],
    hist_events: list[SonarrHistoryEntry],
) -> RequestItem:
    """Build a RequestItem for a series sourced directly from Sonarr.

    Status priority: episodes actively downloading > partial/complete library > history
    fallback. When multiple episodes are queued, ``queue_items[0]`` drives the status
    (it represents the current download) while ``len(queue_items)`` is surfaced as
    ``episodes_queued`` so the UI can show how many episodes are in flight
    simultaneously. Episode counts come from Sonarr's statistics block rather than
    counting queue entries because statistics reflect what is actually on disk.

    Parameters
    ----------
    media : Series
        The Sonarr series object; ``media.statistics`` provides episode file counts.
    queue_items : list[SonarrQueue]
        Active download queue entries for this series (one per in-flight episode).
    hist_events : list[SonarrHistory]
        History events for this series, newest first.

    Returns
    -------
    RequestItem
        Status snapshot for the series, with ``source`` set to ``"sonarr"``.
    """
    ep_total = media.statistics.episode_count if media.statistics else 0
    ep_have = media.statistics.episode_file_count if media.statistics else 0
    item: RequestItem = {
        "id": None,
        "title": media.title,
        "type": "tv",
        "source": "sonarr",
        "requested_by": "Sonarr",
        "requested_at": None,
        "seerr_status": None,
        "arr": None,
        "history": [],
    }
    if queue_items:
        item["arr"] = {
            **arr_queue_status(queue_items[0]),
            "episodes_queued": len(queue_items),
            "episodes": f"{ep_have}/{ep_total}" if ep_total else None,
        }
    elif ep_have > 0:
        status = "available" if ep_have >= ep_total and ep_total > 0 else "partial"
        item["arr"] = {
            "status": status,
            "episodes": f"{ep_have}/{ep_total}",
            "error": None,
        }
        item["history"] = format_history(hist_events[:5])
        item["requested_at"] = hist_events[0].date.isoformat() if hist_events else None
    else:
        item["arr"] = arr_history_status(hist_events)
        item["history"] = format_history(hist_events[:5])
    return item


def is_recent(dt: datetime) -> bool:
    """Return True if ``dt`` falls within the configured history window.

    The ``tzinfo or UTC`` guard is needed because Radarr and Sonarr occasionally
    return naive datetimes from their APIs; treating them as UTC is safe given that
    both services are always UTC-only.

    Parameters
    ----------
    dt : datetime
        The timestamp to test. May be timezone-aware or naive.

    Returns
    -------
    bool
        ``True`` if ``dt`` is within ``HISTORY_WINDOW_DAYS`` of now.
    """
    return (datetime.now(UTC) - dt.replace(tzinfo=dt.tzinfo or UTC)) < timedelta(
        days=HISTORY_WINDOW_DAYS
    )


def seerr_status(req_status: int | None, media_status: int | None) -> str:
    """Derive a display status string from Seerr's request and media status codes.

    ``media_status`` takes precedence because it reflects actual content availability
    in the library independently of the request workflow. Request status codes: 1 =
    pending, 2 = approved, 3 = declined, 4 = completed. Media status codes: 4 =
    partial, 5 = available.

    Parameters
    ----------
    req_status : int or None
        Jellyseerr request status code. ``None`` if the item has no associated request.
    media_status : int or None
        Jellyseerr media status code. ``None`` if Jellyseerr has no record of the item.

    Returns
    -------
    str
        One of ``"available"``, ``"partial"``, ``"pending"``, ``"approved"``,
        ``"declined"``, ``"completed"``, or ``"unknown"``.
    """
    if media_status == 5:
        return "available"
    if media_status == 4:
        return "partial"
    return {1: "pending", 2: "approved", 3: "declined", 4: "completed"}.get(req_status, "unknown")


def arr_queue_status(queue_item: ArrQueueEntry) -> ArrStatus:
    """Derive an ArrStatus from a live queue entry.

    Any tracked download state other than Warning or Error is normalised to
    "downloading". The first non-empty status message is surfaced as the error field
    so the UI can show why a download is stalled without exposing the full message list.

    Parameters
    ----------
    queue_item : ArrQueue
        A live Radarr or Sonarr queue entry for a single item.

    Returns
    -------
    ArrStatus
        Status dict with ``"status"`` set to ``"downloading"``, ``"warning"``, or
        ``"error"``, and ``"error"`` set to the first non-empty status message if any.
    """
    error = None
    for msg in queue_item.status_messages:
        if msg.messages:
            error = "; ".join(msg.messages)
            break
    status = queue_item.tracked_download_status
    return {
        "status": "warning"
        if status == "Warning"
        else ("error" if status == "Error" else "downloading"),
        "error": error,
    }


def arr_history_status(
    history: list[ArrHistoryEntry], media_status: int | None = None
) -> ArrStatus:
    """Derive an ArrStatus from the arr history log for an item not in the active queue.

    An empty history means arr accepted the item but has not attempted a download yet,
    so "searching" is the most accurate status. The ``media_status`` short-circuit
    handles items already available in the library that have no active queue entry.

    Parameters
    ----------
    history : list[ArrHistory]
        History events for the item, newest first.
    media_status : int or None, optional
        Seerr media status code. ``5`` (available) short-circuits the history
        lookup and returns immediately.

    Returns
    -------
    ArrStatus
        Status dict derived from the most recent history event, or ``"searching"``
        if no history exists yet.
    """
    if media_status == 5:
        return {"status": "available", "error": None}
    if not history:
        return {"status": "searching", "error": None}
    latest = history[0]
    event_map = {
        "grabbed": "grabbed",
        "downloadFailed": "failed",
        "downloadFolderImported": "imported",
        "downloadIgnored": "ignored",
    }
    status = event_map.get(latest.event_type, latest.event_type)
    error = latest.data.get("message") or latest.source_title if status == "failed" else None
    return {"status": status, "error": error, "at": latest.date.isoformat()}


def format_history(events: list[ArrHistoryEntry]) -> list[HistoryEvent]:
    """Flatten arr history records into the HistoryEvent shape expected by the template.

    Strips the full ArrHistory model down to the four fields the template actually
    uses, keeping the template layer decoupled from the arr model's internal shape.
    Without this boundary, any change to ArrHistory risks bleeding through to the
    presentation layer.

    Parameters
    ----------
    events : list[ArrHistory]
        Arr history events to convert. Typically a slice of the full history list
        (e.g. the five most recent events).

    Returns
    -------
    list[HistoryEvent]
        One dict per event, containing ``event``, ``at``, ``source``, and ``error``.
    """
    return [
        {
            "event": e.event_type,
            "at": e.date.isoformat(),
            "source": e.source_title,
            "error": e.data.get("message") or e.source_title
            if e.event_type == "downloadFailed"
            else None,
        }
        for e in events
    ]
