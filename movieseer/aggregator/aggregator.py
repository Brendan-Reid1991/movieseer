"""Aggregator: fetches and merges status from all downstream services."""

from __future__ import annotations

import asyncio
import logging
import time

from movieseer.aggregator._utils import (
    arr_history_status,
    arr_queue_status,
    format_history,
    is_recent,
    jellyseerr_status,
    movie_requests,
    series_requests,
)
from movieseer.aggregator.services.jellyseer import JellyseerClient
from movieseer.aggregator.services.models.jellyseer_models import MediaRequest
from movieseer.aggregator.services.prowlarr import ProwlarrClient
from movieseer.aggregator.services.qbittorrent import QBittorrentClient
from movieseer.aggregator.services.radarr import (
    RadarrClient,
    RadarrHistory,
    RadarrQueue,
)
from movieseer.aggregator.services.sabnzbd import SABnzbdClient
from movieseer.aggregator.services.sonarr import (
    SonarrClient,
    SonarrHistory,
    SonarrQueue,
)
from movieseer.aggregator.types import (
    RequestItem,
    StatusResult,
    SystemStatus,
)
from movieseer.config import CACHE_TTL

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

        req: MediaRequest
        for req in js_requests:
            try:
                item = await self._build_jellyseerr_request(req, radarr_queue, sonarr_queue)
                results.append(item)
                if req.media.external_service_id:
                    if req.type == "movie":
                        js_movie_ids.add(req.media.external_service_id)
                    else:
                        js_series_ids.add(req.media.external_service_id)
            except Exception as exc:
                logger.warning("Jellyseerr item %s build failed: %s", req.id, exc)

        direct = await self._get_direct_items(
            js_movie_ids, js_series_ids, radarr_queue, sonarr_queue
        )
        results.extend(direct)

        # Sort by request date where available, falling back to most recent arr
        # history event. These measure different things but both approximate
        # "when activity last occurred", which is good enough for a dashboard.
        results.sort(
            key=lambda item: item["requested_at"] or (item["arr"] or {}).get("at") or "",
            reverse=True,
        )
        return results[:10]

    async def _build_jellyseerr_request(
        self,
        request: MediaRequest,
        radarr_queue: list[RadarrQueue],
        sonarr_queue: list[SonarrQueue],
    ) -> RequestItem:
        """Build a normalised RequestItem from a single Jellyseerr request.

        When ``external_service_id`` is absent the request hasn't reached Radarr/Sonarr
        yet (still pending approval or queued in Jellyseerr), so we fall back to
        Jellyseerr's own media detail for title enrichment and return early regardless
        of whether that lookup succeeds.

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
            "jellyseerr_status": jellyseerr_status(request.status, request.media.status),
            "arr": None,
            "history": [],
        }

        arr_id = request.media.external_service_id
        if not arr_id:
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
            await self._enrich_movie(item, arr_id, radarr_queue, request.media.status)
        elif request.type == "tv":
            await self._enrich_tv(item, arr_id, sonarr_queue, request.media.status)
        else:
            raise ValueError(f"Unknown request type: {request.type}")

        return item

    async def _enrich_movie(
        self,
        item: RequestItem,
        arr_id: int,
        radarr_queue: list[RadarrQueue],
        media_status: int | None,
    ) -> None:
        """Populate ``item`` with Radarr queue or history data for a movie.

        Checks the pre-fetched queue first; if the movie is actively downloading
        we populate from the queue entry and return. Otherwise we fetch the movie
        record and its history from Radarr. Failures are logged and ``item`` is
        left with ``arr=None``.
        """
        queue_item = next((q for q in radarr_queue if q.movie_id == arr_id), None)
        if queue_item:
            item["arr"] = arr_queue_status(queue_item)
            item["title"] = (queue_item.movie.title if queue_item.movie else None) or item["title"]
            return
        try:
            movie, history = await asyncio.gather(
                self._radarr.movie(arr_id),
                self._radarr.movie_history(arr_id),
            )
            item["title"] = movie.title or item["title"]
            item["arr"] = arr_history_status(history, media_status)
            item["history"] = format_history(history[:5])
        except Exception as e:
            logger.warning("Radarr movie lookup failed for id %s: %s", arr_id, e)

    async def _enrich_tv(
        self,
        item: RequestItem,
        arr_id: int,
        sonarr_queue: list[SonarrQueue],
        media_status: int | None,
    ) -> None:
        """Populate ``item`` with Sonarr queue or history data for a TV series.

        Checks the pre-fetched queue first; if episodes are actively downloading
        we populate from the queue entries (including episode count) and return.
        Otherwise we fetch the series record and its history from Sonarr. Failures
        are logged and ``item`` is left with ``arr=None``.
        """
        queue_items = [q for q in sonarr_queue if q.series_id == arr_id]
        if queue_items:
            item["arr"] = {**arr_queue_status(queue_items[0]), "episodes_queued": len(queue_items)}
            item["title"] = (
                queue_items[0].series.title if queue_items[0].series else None
            ) or item["title"]
            return
        try:
            series, history = await asyncio.gather(
                self._sonarr.series(arr_id),
                self._sonarr.series_history(arr_id),
            )
            item["title"] = series.title or item["title"]
            item["arr"] = arr_history_status(history, media_status)
            item["history"] = format_history(history[:5])
        except Exception as e:
            logger.warning("Sonarr series lookup failed for id %s: %s", arr_id, e)

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
        radarr_hist: list[RadarrHistory] | Exception
        sonarr_hist: list[SonarrHistory] | Exception

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
            e.movie_id for e in radarr_hist if is_recent(e.date)
        }
        sonarr_ids = {q.series_id for q in sonarr_queue if q.series_id} | {
            e.series_id for e in sonarr_hist if is_recent(e.date)
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

        return movie_requests(
            movie_ids, movie_details, radarr_queue, radarr_hist
        ) + series_requests(series_ids, series_details, sonarr_queue, sonarr_hist)
