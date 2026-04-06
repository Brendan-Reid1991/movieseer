"""Aggregator: fetches and merges status from all downstream services."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

import httpx

from movieseer.aggregator.services.arr_models import ArrHistory
from movieseer.aggregator.services.prowlarr import ProwlarrClient
from movieseer.aggregator.services.qbittorrent import QBittorrentClient
from movieseer.aggregator.services.radarr import RadarrClient
from movieseer.aggregator.services.sabnzbd import SABnzbdClient
from movieseer.aggregator.services.sonarr import SonarrClient
from movieseer.aggregator.types import (
    ArrStatus,
    HistoryEvent,
    RequestItem,
    StatusResult,
    SystemStatus,
)
from movieseer.config import (
    CACHE_TTL,
    HISTORY_WINDOW_DAYS,
    JELLYSEERR_API_KEY,
    JELLYSEERR_URL,
)

logger = logging.getLogger(__name__)


class Aggregator:
    """Aggregates status data from Jellyseerr, Radarr, Sonarr, Prowlarr, SABnzbd,
    and qBittorrent.

    Each downstream service has its own long-lived HTTP client, created at
    construction and reused across all poll cycles. Call ``aclose()`` on
    shutdown to release connections cleanly.

    Attributes
    ----------
    _cache : StatusResult or None
        The most recently fetched result, or ``None`` if the cache has
        never been populated or has been explicitly invalidated.
    _cache_time : float
        ``time.monotonic()`` timestamp of the last successful fetch.
    """

    def __init__(self) -> None:
        self._radarr = RadarrClient()
        self._sonarr = SonarrClient()
        self._prowlarr = ProwlarrClient()
        self._sabnzbd = SABnzbdClient()
        self._qbit = QBittorrentClient()
        self._cache: StatusResult | None = None
        self._cache_time: float = 0.0

    async def aclose(self) -> None:
        """Close all service clients and release their connections."""
        await asyncio.gather(
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
        """Fetch the aggregated system and request status, using a cache where possible.

        Returns
        -------
        StatusResult
            Dictionary containing ``system`` (Prowlarr/SABnzbd/qBittorrent health)
            and ``requests`` (enriched Jellyseerr + direct Radarr/Sonarr items).

        Notes
        -----
        Results are cached for ``CACHE_TTL`` seconds. Individual subsystem failures
        are caught and embedded as ``{"error": "..."}`` rather than propagating.
        """
        now = time.monotonic()
        if self._cache and (now - self._cache_time) < CACHE_TTL:
            return self._cache

        system, requests = await asyncio.gather(
            self._get_system(),
            self._get_requests(),
            return_exceptions=True,
        )

        if isinstance(system, Exception):
            logger.warning("System fetch failed: %s", system)
        if isinstance(requests, Exception):
            logger.warning("Requests fetch failed: %s", requests)

        result: StatusResult = {
            "system": system
            if not isinstance(system, Exception)
            else {"error": str(system)},
            "requests": requests if not isinstance(requests, Exception) else [],
        }
        self._cache = result
        self._cache_time = now
        return result

    # ── system status ─────────────────────────────────────────────────────────

    async def _get_system(self) -> SystemStatus:
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
            "sabnzbd": sabnzbd
            if not isinstance(sabnzbd, Exception)
            else {"error": str(sabnzbd)},
            "qbittorrent": qbit
            if not isinstance(qbit, Exception)
            else {"error": str(qbit)},
        }

    # ── requests ───────────────────────────────────────────────────────────────

    async def _get_requests(self) -> list[RequestItem]:
        """Build the full list of in-progress media requests.

        Fetches the 20 most recent Jellyseerr requests, enriches each with
        Radarr/Sonarr queue and history data, then appends items that were
        added directly in Radarr or Sonarr (i.e. have no Jellyseerr request).
        Results are sorted newest-first by request or activity date.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{JELLYSEERR_URL}/api/v1/request",
                params={"take": 20, "sort": "added"},
                headers={"X-Api-Key": JELLYSEERR_API_KEY},
            )
        r.raise_for_status()
        js_requests = r.json().get("results", [])

        radarr_queue, sonarr_queue = await asyncio.gather(
            self._radarr.queue(),
            self._sonarr.queue(),
            return_exceptions=True,
        )
        if isinstance(radarr_queue, Exception):
            logger.warning("Radarr queue fetch failed: %s", radarr_queue)
            radarr_queue = []
        if isinstance(sonarr_queue, Exception):
            logger.warning("Sonarr queue fetch failed: %s", sonarr_queue)
            sonarr_queue = []

        results: list[RequestItem] = []
        js_movie_ids: set[int] = set()
        js_series_ids: set[int] = set()

        for req in js_requests:
            item = await self._build_js_item(req, radarr_queue, sonarr_queue)
            results.append(item)
            arr_id = req.get("media", {}).get("externalServiceId")
            if arr_id:
                if req.get("type") == "movie":
                    js_movie_ids.add(arr_id)
                else:
                    js_series_ids.add(arr_id)

        direct = await self._get_direct_items(
            js_movie_ids,
            js_series_ids,
            radarr_queue,
            sonarr_queue,
        )
        results.extend(direct)

        results.sort(
            key=lambda item: (
                item.get("requested_at") or (item.get("arr") or {}).get("at") or ""
            ),
            reverse=True,
        )
        return results

    async def _build_js_item(
        self,
        req: dict[str, object],
        radarr_queue: list,
        sonarr_queue: list,
    ) -> RequestItem:
        """Build a normalised RequestItem from a single Jellyseerr request."""
        media = req.get("media", {})
        media_type = req.get("type", "movie")
        arr_id = media.get("externalServiceId")

        item: RequestItem = {
            "id": req.get("id"),
            "title": media.get("originalTitle") or media.get("title", "Unknown"),
            "type": media_type,
            "source": "jellyseerr",
            "requested_by": req.get("requestedBy", {}).get("displayName", "?"),
            "requested_at": req.get("createdAt"),
            "jellyseerr_status": self._js_status(req.get("status"), media.get("status")),
            "arr": None,
            "download": None,
            "history": [],
        }

        if not arr_id:
            tmdb_id = media.get("tmdbId")
            endpoint = "tv" if media_type == "tv" else "movie"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(
                        f"{JELLYSEERR_URL}/api/v1/{endpoint}/{tmdb_id}",
                        headers={"X-Api-Key": JELLYSEERR_API_KEY},
                    )
                if r.status_code == 200:
                    d = r.json()
                    item["title"] = d.get("title") or d.get("name") or item["title"]
            except Exception as e:
                logger.warning(
                    "Jellyseerr title lookup failed for %s %s: %s",
                    media_type,
                    tmdb_id,
                    e,
                )
            return item

        if media_type == "movie":
            queue_item = next((q for q in radarr_queue if q.movie_id == arr_id), None)
            if queue_item:
                item["arr"] = self._arr_queue_status(queue_item)
                item["title"] = (
                    queue_item.movie.title if queue_item.movie else None
                ) or item["title"]
            else:
                try:
                    movie = await self._radarr.movie(arr_id)
                    item["title"] = movie.title or item["title"]
                    history = await self._radarr.movie_history(arr_id)
                    item["arr"] = self._arr_history_status(history, media)
                    item["history"] = self._format_history(history[:5])
                except Exception as e:
                    logger.warning("Radarr movie lookup failed for id %s: %s", arr_id, e)

        elif media_type == "tv":
            queue_items = [q for q in sonarr_queue if q.series_id == arr_id]
            if queue_items:
                item["arr"] = {
                    "status": "downloading",
                    "episodes_queued": len(queue_items),
                    "error": None,
                }
                item["title"] = (
                    queue_items[0].series.title if queue_items[0].series else None
                ) or item["title"]
            else:
                try:
                    series = await self._sonarr.series(arr_id)
                    item["title"] = series.title or item["title"]
                    history = await self._sonarr.series_history(arr_id)
                    item["arr"] = self._arr_history_status(history, media)
                    item["history"] = self._format_history(history[:5])
                except Exception as e:
                    logger.warning(
                        "Sonarr series lookup failed for id %s: %s", arr_id, e
                    )

        return item

    # ── direct items (Radarr/Sonarr, not via Jellyseerr) ─────────────────────

    async def _get_direct_items(
        self,
        js_movie_ids: set[int],
        js_series_ids: set[int],
        radarr_queue: list,
        sonarr_queue: list,
    ) -> list[RequestItem]:
        """Fetch items added directly in Radarr/Sonarr with no Jellyseerr request."""
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

        untracked_movie_ids: set[int] = set()
        untracked_series_ids: set[int] = set()

        for q in radarr_queue:
            if q.movie_id and q.movie_id not in js_movie_ids:
                untracked_movie_ids.add(q.movie_id)

        for q in sonarr_queue:
            if q.series_id and q.series_id not in js_series_ids:
                untracked_series_ids.add(q.series_id)

        for event in radarr_hist:
            if event.movie_id not in js_movie_ids and self._is_recent(event.date):
                untracked_movie_ids.add(event.movie_id)

        for event in sonarr_hist:
            if event.series_id not in js_series_ids and self._is_recent(event.date):
                untracked_series_ids.add(event.series_id)

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

        results: list[RequestItem] = []

        for i, mid in enumerate(movie_ids):
            detail = (
                movie_details[i] if not isinstance(movie_details[i], Exception) else None
            )
            if not detail:
                continue
            queue_item = next((q for q in radarr_queue if q.movie_id == mid), None)
            hist_events = [e for e in radarr_hist if e.movie_id == mid]

            item: RequestItem = {
                "id": None,
                "title": detail.title,
                "type": "movie",
                "source": "radarr",
                "requested_by": "Radarr",
                "requested_at": None,
                "jellyseerr_status": None,
                "arr": None,
                "download": None,
                "history": [],
            }

            if queue_item:
                item["arr"] = self._arr_queue_status(queue_item)
            elif detail.has_file:
                item["arr"] = {"status": "imported", "error": None}
                item["history"] = self._format_history(hist_events[:5])
                item["requested_at"] = (
                    hist_events[0].date.isoformat() if hist_events else None
                )
            else:
                item["arr"] = self._arr_history_status(hist_events, {})
                item["history"] = self._format_history(hist_events[:5])

            results.append(item)

        for i, sid in enumerate(series_ids):
            detail = (
                series_details[i]
                if not isinstance(series_details[i], Exception)
                else None
            )
            if not detail:
                continue
            queue_items = [q for q in sonarr_queue if q.series_id == sid]
            hist_events = [e for e in sonarr_hist if e.series_id == sid]
            ep_total = detail.statistics.episode_count if detail.statistics else 0
            ep_have = detail.statistics.episode_file_count if detail.statistics else 0

            item = {
                "id": None,
                "title": detail.title,
                "type": "tv",
                "source": "sonarr",
                "requested_by": "Sonarr",
                "requested_at": None,
                "jellyseerr_status": None,
                "arr": None,
                "download": None,
                "history": [],
            }

            if queue_items:
                item["arr"] = {
                    "status": "downloading",
                    "episodes_queued": len(queue_items),
                    "episodes": f"{ep_have}/{ep_total}" if ep_total else None,
                    "error": None,
                }
            elif ep_have > 0:
                status = (
                    "available" if ep_have >= ep_total and ep_total > 0 else "partial"
                )
                item["arr"] = {
                    "status": status,
                    "episodes": f"{ep_have}/{ep_total}",
                    "error": None,
                }
                item["history"] = self._format_history(hist_events[:5])
                item["requested_at"] = (
                    hist_events[0].date.isoformat() if hist_events else None
                )
            else:
                item["arr"] = self._arr_history_status(hist_events, {})
                item["history"] = self._format_history(hist_events[:5])

            results.append(item)

        return results

    # ── status helpers ────────────────────────────────────────────────────────

    def _is_recent(self, dt: datetime) -> bool:
        """Return True if *dt* falls within the configured history window."""
        return (datetime.now(UTC) - dt.replace(tzinfo=dt.tzinfo or UTC)) < timedelta(
            days=HISTORY_WINDOW_DAYS
        )

    def _js_status(self, req_status: int | None, media_status: int | None) -> str:
        if media_status == 5:
            return "available"
        if media_status == 4:
            return "partial"
        return {1: "pending", 2: "approved", 3: "declined"}.get(req_status, "unknown")

    def _arr_queue_status(self, queue_item: ArrQueue) -> ArrStatus:
        """Derive an ArrStatus from an active Radarr or Sonarr queue record."""
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

    def _arr_history_status(
        self, history: list[ArrHistory], media: dict[str, object]
    ) -> ArrStatus:
        """Derive an ArrStatus from a Radarr or Sonarr history event list."""
        if media.get("status") == 5:
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
        error = None
        if status == "failed":
            error = latest.data.get("message") or latest.source_title
        return {"status": status, "error": error, "at": latest.date.isoformat()}

    def _format_history(self, events: list[ArrHistory]) -> list[HistoryEvent]:
        """Convert arr history events to a simplified format."""
        out: list[HistoryEvent] = []
        for e in events:
            error = None
            if e.event_type == "downloadFailed":
                error = e.data.get("message") or e.source_title
            out.append(
                {
                    "event": e.event_type,
                    "at": e.date.isoformat(),
                    "source": e.source_title,
                    "error": error,
                }
            )
        return out
