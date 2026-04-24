"""Aggregator: fetches and merges status from all downstream services."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from movieseer.aggregator.services.jellyseer import JellyseerClient
from movieseer.aggregator.services.models.arr_models import ArrHistory, ArrQueue
from movieseer.aggregator.services.models.jellyseer_models import MediaRequest
from movieseer.aggregator.services.prowlarr import ProwlarrClient
from movieseer.aggregator.services.qbittorrent import QBittorrentClient
from movieseer.aggregator.services.radarr import (
    Movie,
    RadarrClient,
    RadarrHistory,
    RadarrQueue,
)
from movieseer.aggregator.services.sabnzbd import SABnzbdClient
from movieseer.aggregator.services.sonarr import (
    Series,
    SonarrClient,
    SonarrHistory,
    SonarrQueue,
)
from movieseer.aggregator.types import (
    ArrStatus,
    HistoryEvent,
    RequestItem,
    StatusResult,
    SystemStatus,
)
from movieseer.config import CACHE_TTL, HISTORY_WINDOW_DAYS

logger = logging.getLogger(__name__)


class Aggregator:
    """Aggregates status data from Jellyseerr, Radarr, Sonarr, Prowlarr, SABnzbd,
    and qBittorrent.

    Each downstream service has its own long-lived HTTP client, created at
    construction and reused across all poll cycles. Call ``aclose()`` on
    shutdown to release connections cleanly.
    """

    def __init__(self) -> None:
        self._jellyseer = JellyseerClient()
        self._radarr = RadarrClient()
        self._sonarr = SonarrClient()
        self._prowlarr = ProwlarrClient()
        self._sabnzbd = SABnzbdClient()
        self._qbit = QBittorrentClient()

        self._cache: StatusResult | None = None
        self._cache_time: float = 0.0
        self._cache_lock = asyncio.Lock()

    async def aclose(self) -> None:
        """Close all service clients and release their connections."""
        await asyncio.gather(
            self._jellyseer.aclose(),
            self._radarr.aclose(),
            self._sonarr.aclose(),
            self._prowlarr.aclose(),
            self._sabnzbd.aclose(),
            self._qbit.aclose(),
        )

    def invalidate_cache(self) -> None:
        """Force the next call to ``get_status`` to bypass the in-memory cache."""
        self._cache_time = 0.0

    async def get_status(self) -> StatusResult:
        """Fetch the aggregated system and request status, using a cache where possible."""
        now = time.monotonic()
        if self._cache and (now - self._cache_time) < CACHE_TTL:
            return self._cache

        async with self._cache_lock:
            now = time.monotonic()
            if self._cache and (now - self._cache_time) < CACHE_TTL:
                return self._cache

            system, requests = await asyncio.gather(
                self._get_system(),
                self._get_requests(),
            )

            result: StatusResult = {"system": system, "requests": requests}
            self._cache = result
            self._cache_time = now
            return result

    # ── system status ─────────────────────────────────────────────────────────

    async def _get_system(self) -> SystemStatus:
        """Fetch live status from Prowlarr, SABnzbd, and qBittorrent in parallel.

        Failures are passed through as ``{"error": "..."}`` rather than raising,
        so a single unreachable service does not blank the whole dashboard.
        """
        prowlarr, sabnzbd, qbit = await asyncio.gather(
            self._prowlarr.status(),
            self._sabnzbd.queue(),
            self._qbit.torrents(),
            return_exceptions=True,
        )

        if not isinstance(sabnzbd, Exception):
            sabnzbd = sabnzbd.model_copy(update={"slots": sabnzbd.slots[:5]})
        if not isinstance(qbit, Exception):
            qbit = sorted(
                [t for t in qbit.values() if "download" in t.state.lower()],
                key=lambda t: t.progress,
                reverse=True,
            )[:5]

        return {
            "prowlarr": prowlarr
            if not isinstance(prowlarr, Exception)
            else {"error": str(prowlarr)},
            "sabnzbd": sabnzbd if not isinstance(sabnzbd, Exception) else {"error": str(sabnzbd)},
            "qbittorrent": qbit if not isinstance(qbit, Exception) else {"error": str(qbit)},
        }

    # ── requests ───────────────────────────────────────────────────────────────

    async def _get_requests(self) -> list[RequestItem]:
        """Build the full list of in-progress media requests.

        Fetches Jellyseerr requests and Radarr/Sonarr queues in parallel, enriches
        each Jellyseerr item with queue/history data, then appends items that were
        added directly in Radarr or Sonarr. Results are sorted newest-first.
        """
        radarr_queue, sonarr_queue, js_requests = await asyncio.gather(
            self._radarr.queue(),
            self._sonarr.queue(),
            self._jellyseer.requests(take=10),
            return_exceptions=True,
        )
        if isinstance(radarr_queue, Exception):
            logger.warning("Radarr queue fetch failed: %s", radarr_queue)
            radarr_queue = []
        if isinstance(sonarr_queue, Exception):
            logger.warning("Sonarr queue fetch failed: %s", sonarr_queue)
            sonarr_queue = []
        if isinstance(js_requests, Exception):
            logger.warning("Jellyseerr requests fetch failed: %s", js_requests)
            js_requests = []

        results: list[RequestItem] = []
        js_movie_ids: set[int] = set()
        js_series_ids: set[int] = set()

        requests: list[MediaRequest] = js_requests
        for req in requests:
            try:
                item = await self._build_jellyseerr_item(req, radarr_queue, sonarr_queue)
                results.append(item)
                if req.media.external_service_id:
                    if req.type == "movie":
                        js_movie_ids.add(req.media.external_service_id)
                    else:
                        js_series_ids.add(req.media.external_service_id)
            except Exception as exc:
                logger.warning(f"Jellyseerr item {req.id} build failed: {exc}")

        direct = await self._get_direct_items(
            js_movie_ids, js_series_ids, radarr_queue, sonarr_queue
        )
        results.extend(direct)

        # Sort by request date where available, falling back to most recent arr
        # history event. These measure different things but both approximate
        # "when activity last occurred", which is good enough for a dashboard.
        results.sort(
            key=lambda item: item.get("requested_at") or (item.get("arr") or {}).get("at") or "",
            reverse=True,
        )
        return results[:10]

    async def _build_jellyseerr_item(
        self,
        request: MediaRequest,
        radarr_queue: list[RadarrQueue],
        sonarr_queue: list[SonarrQueue],
    ) -> RequestItem:
        """Build a normalised RequestItem from a single Jellyseerr request.

        When ``external_service_id`` is absent the request hasn't reached Radarr/Sonarr
        yet (still pending approval or queued in Jellyseerr), so we fall back to
        Jellyseerr's own media detail for title enrichment and return early.

        When an arr ID is present, queue data is preferred over history because it
        reflects the live download state; history is only fetched when the item isn't
        actively downloading.
        """
        item: RequestItem = {
            "id": request.id,
            "title": request.media.original_title or request.media.title or "Unknown",
            "type": request.type,
            "source": "jellyseerr",
            "requested_by": request.requested_by.display_name or "?",
            "requested_at": request.created_at.isoformat(),
            "jellyseerr_status": _jellyseerr_status(request.status, request.media.status),
            "arr": None,
            "history": [],
        }

        arr_id = request.media.external_service_id
        if not arr_id:
            # In this branch, Radarr or Sonarr have not picked up the media yet
            # So we have to rely on jellyseerr for info.
            try:
                detail = await self._jellyseer.media_detail(request.type, request.media.tmdb_id)
                item["title"] = detail.title or detail.name or item["title"]
            except Exception as e:
                logger.warning(
                    "Jellyseerr title lookup failed for %s %s: %s",
                    request.type,
                    request.media.tmdb_id,
                    e,
                )
            return item

        if request.type == "movie":
            queue_item = next((q for q in radarr_queue if q.movie_id == arr_id), None)
            if queue_item:
                item["arr"] = _arr_queue_status(queue_item)
                item["title"] = (queue_item.movie.title if queue_item.movie else None) or item[
                    "title"
                ]
            else:
                try:
                    movie, history = await asyncio.gather(
                        self._radarr.movie(arr_id),
                        self._radarr.movie_history(arr_id),
                    )
                    item["title"] = movie.title or item["title"]
                    item["arr"] = _arr_history_status(history, request.media.status)
                    item["history"] = _format_history(history[:5])
                except Exception as e:
                    logger.warning("Radarr movie lookup failed for id %s: %s", arr_id, e)

        elif request.type == "tv":
            queue_items = [q for q in sonarr_queue if q.series_id == arr_id]
            if queue_items:
                item["arr"] = {
                    **_arr_queue_status(queue_items[0]),
                    "episodes_queued": len(queue_items),
                }
                item["title"] = (
                    queue_items[0].series.title if queue_items[0].series else None
                ) or item["title"]
            else:
                try:
                    series, history = await asyncio.gather(
                        self._sonarr.series(arr_id),
                        self._sonarr.series_history(arr_id),
                    )
                    item["title"] = series.title or item["title"]
                    item["arr"] = _arr_history_status(history, request.media.status)
                    item["history"] = _format_history(history[:5])
                except Exception as e:
                    logger.warning("Sonarr series lookup failed for id %s: %s", arr_id, e)
        else:
            raise ValueError(f"Unknown request type: {request.type}")

        return item

    # ── direct items (Radarr/Sonarr, not via Jellyseerr) ─────────────────────

    async def _get_direct_items(
        self,
        js_movie_ids: set[int],
        js_series_ids: set[int],
        radarr_queue: list[RadarrQueue],
        sonarr_queue: list[SonarrQueue],
    ) -> list[RequestItem]:
        """Fetch items added directly in Radarr/Sonarr with no Jellyseerr request.

        Candidates are identified by unioning the active queue with recent history,
        then subtracting the IDs already accounted for by Jellyseerr requests. Detail
        fetches for all candidates run in parallel.
        """
        radarr_hist: list[RadarrHistory]
        sonarr_hist: list[SonarrHistory]
        radarr_hist, sonarr_hist = await asyncio.gather(
            self._radarr.history(),
            self._sonarr.history(),
            return_exceptions=True,
        )
        if isinstance(radarr_hist, Exception):
            logger.warning("Radarr history fetch failed: %s", radarr_hist)
            radarr_hist = []
        if isinstance(sonarr_hist, Exception):
            logger.warning("Sonarr history fetch failed: %s", sonarr_hist)
            sonarr_hist = []

        radarr_ids = {q.movie_id for q in radarr_queue if q.movie_id} | {
            e.movie_id for e in radarr_hist if _is_recent(e.date)
        }
        sonarr_ids = {q.series_id for q in sonarr_queue if q.series_id} | {
            e.series_id for e in sonarr_hist if _is_recent(e.date)
        }

        untracked_movie_ids: set[int] = radarr_ids - js_movie_ids
        untracked_series_ids: set[int] = sonarr_ids - js_series_ids

        if not untracked_movie_ids and not untracked_series_ids:
            return []

        movie_ids = list(untracked_movie_ids)
        series_ids = list(untracked_series_ids)

        movie_details, series_details = await asyncio.gather(
            asyncio.gather(
                *[self._radarr.movie(mid) for mid in movie_ids], return_exceptions=True
            ),
            asyncio.gather(
                *[self._sonarr.series(sid) for sid in series_ids], return_exceptions=True
            ),
        )

        return _collect_movie_items(
            movie_ids, movie_details, radarr_queue, radarr_hist
        ) + _collect_series_items(
            series_ids, series_details, sonarr_queue, sonarr_hist
        )


def _collect_movie_items(
    ids: list[int],
    details: list[Movie | BaseException],
    queue: list[RadarrQueue],
    hist: list[RadarrHistory],
) -> list[RequestItem]:
    results = []
    for movie_id, movie in zip(ids, details):
        if isinstance(movie, BaseException):
            logger.warning("Radarr movie lookup failed for id %s: %s", movie_id, movie)
            continue
        results.append(_build_direct_movie_item(
            movie,
            next((q for q in queue if q.movie_id == movie_id), None),
            [e for e in hist if e.movie_id == movie_id],
        ))
    return results


def _collect_series_items(
    ids: list[int],
    details: list[Series | BaseException],
    queue: list[SonarrQueue],
    hist: list[SonarrHistory],
) -> list[RequestItem]:
    results = []
    for sid, series in zip(ids, details):
        if isinstance(series, BaseException):
            logger.warning("Sonarr series lookup failed for id %s: %s", sid, series)
            continue
        results.append(_build_direct_series_item(
            series,
            [q for q in queue if q.series_id == sid],
            [e for e in hist if e.series_id == sid],
        ))
    return results


def _build_direct_movie_item(
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
        item["arr"] = _arr_queue_status(queue_item)
    elif media.has_file:
        item["arr"] = {"status": "imported", "error": None}
        item["history"] = _format_history(hist_events[:5])
        item["requested_at"] = hist_events[0].date.isoformat() if hist_events else None
    else:
        item["arr"] = _arr_history_status(hist_events)
        item["history"] = _format_history(hist_events[:5])
    return item


def _build_direct_series_item(
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
            **_arr_queue_status(queue_items[0]),
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
        item["history"] = _format_history(hist_events[:5])
        item["requested_at"] = hist_events[0].date.isoformat() if hist_events else None
    else:
        item["arr"] = _arr_history_status(hist_events)
        item["history"] = _format_history(hist_events[:5])
    return item


def _is_recent(dt: datetime) -> bool:
    """Return True if ``dt`` falls within the configured history window.

    Arr history timestamps are UTC; naive datetimes from the API are treated as UTC.
    """
    return (datetime.now(UTC) - dt.replace(tzinfo=dt.tzinfo or UTC)) < timedelta(
        days=HISTORY_WINDOW_DAYS
    )


def _jellyseerr_status(req_status: int | None, media_status: int | None) -> str:
    """Derive a display status string from Jellyseerr's request and media status codes.

    ``media_status`` takes precedence because it reflects actual content availability
    in the library (4 = partial, 5 = available), independent of the request workflow.
    """
    if media_status == 5:
        return "available"
    if media_status == 4:
        return "partial"
    return {1: "pending", 2: "approved", 3: "declined", 4: "completed"}.get(req_status, "unknown")


def _arr_queue_status(queue_item: ArrQueue) -> ArrStatus:
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


def _arr_history_status(history: list[ArrHistory], media_status: int | None = None) -> ArrStatus:
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


def _format_history(events: list[ArrHistory]) -> list[HistoryEvent]:
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
