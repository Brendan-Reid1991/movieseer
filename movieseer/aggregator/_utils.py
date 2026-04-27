from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from movieseer.aggregator.services.models.arr_models import ArrHistory, ArrQueue
from movieseer.aggregator.services.radarr import (
    Movie,
    RadarrHistory,
    RadarrQueue,
)
from movieseer.aggregator.services.sonarr import (
    Series,
    SonarrHistory,
    SonarrQueue,
)
from movieseer.aggregator.types import (
    ArrStatus,
    HistoryEvent,
    RequestItem,
)
from movieseer.config import HISTORY_WINDOW_DAYS

logger = logging.getLogger(__name__)


def movie_requests(
    ids: list[int],
    details: list[Movie | BaseException],
    queue: list[RadarrQueue],
    hist: list[RadarrHistory],
) -> list[RequestItem]:
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
    queue: list[SonarrQueue],
    hist: list[SonarrHistory],
) -> list[RequestItem]:
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
    queue_item: RadarrQueue | None,
    hist_events: list[RadarrHistory],
) -> RequestItem:
    """Build a RequestItem for a movie sourced directly from Radarr.

    Status priority: active queue entry > file already on disk > history fallback.
    """
    item: RequestItem = {
        "id": None,
        "title": media.title,
        "type": "movie",
        "source": "radarr",
        "requested_by": "Radarr",
        "requested_at": None,
        "jellyseerr_status": None,
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
    queue_items: list[SonarrQueue],
    hist_events: list[SonarrHistory],
) -> RequestItem:
    """Build a RequestItem for a series sourced directly from Sonarr.

    Status priority: episodes actively downloading > partial/complete library > history
    fallback. Episode counts come from Sonarr's statistics block.
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
        "jellyseerr_status": None,
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

    Arr history timestamps are UTC; naive datetimes from the API are treated as UTC.
    """
    return (datetime.now(UTC) - dt.replace(tzinfo=dt.tzinfo or UTC)) < timedelta(
        days=HISTORY_WINDOW_DAYS
    )


def jellyseerr_status(req_status: int | None, media_status: int | None) -> str:
    """Derive a display status string from Jellyseerr's request and media status codes.

    ``media_status`` takes precedence because it reflects actual content availability
    in the library (4 = partial, 5 = available), independent of the request workflow.
    """
    if media_status == 5:
        return "available"
    if media_status == 4:
        return "partial"
    return {1: "pending", 2: "approved", 3: "declined", 4: "completed"}.get(req_status, "unknown")


def arr_queue_status(queue_item: ArrQueue) -> ArrStatus:
    """Derive an ArrStatus from a live queue entry.

    Any tracked download state other than Warning or Error is normalised to
    "downloading". The first non-empty status message is surfaced as the error.
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


def arr_history_status(history: list[ArrHistory], media_status: int | None = None) -> ArrStatus:
    """Derive an ArrStatus from the arr history log for an item not in the active queue.

    An empty history means arr accepted the item but hasn't attempted a download yet,
    so "searching" is the most accurate status. The ``media_status`` short-circuit
    handles items already available in the library.
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
        "movieFolderImported": "imported",
        "downloadIgnored": "ignored",
    }
    status = event_map.get(latest.event_type, latest.event_type)
    error = latest.data.get("message") or latest.source_title if status == "failed" else None
    return {"status": status, "error": error, "at": latest.date.isoformat()}


def format_history(events: list[ArrHistory]) -> list[HistoryEvent]:
    """Flatten arr history records into the HistoryEvent shape expected by the template."""
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
