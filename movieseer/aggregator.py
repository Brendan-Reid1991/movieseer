import asyncio
import logging
import httpx
import time
from datetime import datetime, timezone, timedelta
from typing import TypedDict

logger = logging.getLogger(__name__)

from movieseer.config import (
    JELLYSEERR_URL, JELLYSEERR_API_KEY,
    RADARR_URL, RADARR_API_KEY,
    SONARR_URL, SONARR_API_KEY,
    PROWLARR_URL, PROWLARR_API_KEY,
    SABNZBD_URL, SABNZBD_API_KEY,
    QBITTORRENT_URL, QBITTORRENT_USER, QBITTORRENT_PASS,
    CACHE_TTL, HISTORY_WINDOW_DAYS,
)


# ── TypedDicts ────────────────────────────────────────────────────────────────

class ProwlarrIssue(TypedDict):
    name: str
    message: str


class ProwlarrStatus(TypedDict):
    total: int
    failing: int
    healthy: int
    issues: list[ProwlarrIssue]


class SabnzbdSlotSummary(TypedDict):
    name: str
    progress: float
    eta: str
    status: str


class SabnzbdSummary(TypedDict):
    count: int
    speed: str
    eta: str
    paused: bool
    slots: list[SabnzbdSlotSummary]


class QbitSummary(TypedDict):
    active: int
    downloading: int


class SystemStatus(TypedDict):
    prowlarr: ProwlarrStatus | dict[str, str]
    sabnzbd: SabnzbdSummary | dict[str, str]
    qbittorrent: QbitSummary | dict[str, str]


class _ArrStatusBase(TypedDict):
    status: str
    error: str | None


class ArrStatus(_ArrStatusBase, total=False):
    at: str | None
    episodes_queued: int
    episodes: str | None


class DownloadInfo(TypedDict):
    client: str
    name: str
    progress: float
    status: str
    eta: str
    error: str | None


class HistoryEvent(TypedDict):
    event: str
    at: str | None
    source: str
    error: str | None


class RequestItem(TypedDict):
    id: int | None
    title: str
    type: str
    source: str
    requested_by: str
    requested_at: str | None
    jellyseerr_status: str | None
    arr: ArrStatus | None
    download: DownloadInfo | None
    history: list[HistoryEvent]


class StatusResult(TypedDict):
    system: SystemStatus | dict[str, str]
    requests: list[RequestItem]


class Aggregator:
    """Aggregates status data from Jellyseerr, Radarr, Sonarr, Prowlarr, SABnzbd, and qBittorrent.

    Fetches and merges media request status, download queue state, and
    indexer health into a single normalised response. Results are cached
    in memory for ``CACHE_TTL`` seconds to avoid hammering the downstream
    APIs on every poll.

    Attributes
    ----------
    _cache : StatusResult or None
        The most recently fetched result, or ``None`` if the cache has
        never been populated or has been explicitly invalidated.
    _cache_time : float
        ``time.monotonic()`` timestamp of the last successful fetch.
    """

    def __init__(self) -> None:
        self._cache: StatusResult | None = None
        self._cache_time: float = 0.0

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

        async with httpx.AsyncClient(timeout=10.0) as client:
            system, requests = await asyncio.gather(
                self._get_system(client),
                self._get_requests(client),
                return_exceptions=True,
            )

        if isinstance(system, Exception):
            logger.warning("System fetch failed: %s", system)
        if isinstance(requests, Exception):
            logger.warning("Requests fetch failed: %s", requests)

        result: StatusResult = {
            "system": system if not isinstance(system, Exception) else {"error": str(system)},
            "requests": requests if not isinstance(requests, Exception) else [],
        }
        self._cache = result
        self._cache_time = now
        return result

    # ── system status ─────────────────────────────────────────────────────────

    async def _get_system(self, client: httpx.AsyncClient) -> SystemStatus:
        """Fetch and combine status from all download and indexer subsystems.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client for the request lifetime.

        Returns
        -------
        SystemStatus
            Dictionary with keys ``prowlarr``, ``sabnzbd``, and ``qbittorrent``.
            Subsystem failures produce ``{"error": "..."}`` for that key.
        """
        prowlarr, sabnzbd, qbit = await asyncio.gather(
            self._prowlarr_status(client),
            self._sabnzbd_summary(client),
            self._qbit_summary(client),
            return_exceptions=True,
        )
        return {
            "prowlarr": prowlarr if not isinstance(prowlarr, Exception) else {"error": str(prowlarr)},
            "sabnzbd": sabnzbd if not isinstance(sabnzbd, Exception) else {"error": str(sabnzbd)},
            "qbittorrent": qbit if not isinstance(qbit, Exception) else {"error": str(qbit)},
        }

    async def _prowlarr_status(self, client: httpx.AsyncClient) -> ProwlarrStatus:
        """Query the Prowlarr API for indexer health.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client.

        Returns
        -------
        ProwlarrStatus
            Total indexer count, number failing, number healthy, and a list of
            issue details for each failing indexer.

        Raises
        ------
        httpx.HTTPStatusError
            If either Prowlarr API call returns a non-2xx response.
        """
        failing_r, all_r = await asyncio.gather(
            client.get(f"{PROWLARR_URL}/api/v1/indexerstatus", headers={"X-Api-Key": PROWLARR_API_KEY}),
            client.get(f"{PROWLARR_URL}/api/v1/indexer", headers={"X-Api-Key": PROWLARR_API_KEY}),
        )
        failing_r.raise_for_status()
        all_r.raise_for_status()
        failing = failing_r.json()
        total = len(all_r.json())
        return {
            "total": total,
            "failing": len(failing),
            "healthy": total - len(failing),
            "issues": [{"name": i.get("indexerName", "?"), "message": i.get("message", "")} for i in failing],
        }

    async def _sabnzbd_summary(self, client: httpx.AsyncClient) -> SabnzbdSummary:
        """Fetch the SABnzbd download queue summary.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client.

        Returns
        -------
        SabnzbdSummary
            Queue-level metadata (slot count, speed, ETA, pause state) plus
            a per-slot breakdown.

        Raises
        ------
        httpx.HTTPStatusError
            If the SABnzbd API returns a non-2xx response.
        """
        r = await client.get(
            f"{SABNZBD_URL}/api",
            params={"mode": "queue", "apikey": SABNZBD_API_KEY, "output": "json"},
        )
        r.raise_for_status()
        q = r.json()["queue"]
        return {
            "count": int(q.get("noofslots", 0)),
            "speed": q.get("speed", "0"),
            "eta": q.get("timeleft", ""),
            "paused": q.get("paused", False),
            "slots": [
                {
                    "name": s.get("filename", ""),
                    "progress": float(s.get("percentage", 0)),
                    "eta": s.get("timeleft", ""),
                    "status": s.get("status", "").lower(),
                }
                for s in q.get("slots", [])
            ],
        }

    async def _qbit_summary(self, client: httpx.AsyncClient) -> QbitSummary:
        """Fetch an active-torrent summary from qBittorrent.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client. A session cookie is set on the client via the
            login call before fetching torrent info.

        Returns
        -------
        QbitSummary
            Count of active torrents and the subset currently downloading.

        Raises
        ------
        httpx.HTTPStatusError
            If the torrent-info request returns a non-2xx response.
        """
        await client.post(
            f"{QBITTORRENT_URL}/api/v2/auth/login",
            data={"username": QBITTORRENT_USER, "password": QBITTORRENT_PASS},
        )
        r = await client.get(f"{QBITTORRENT_URL}/api/v2/torrents/info", params={"filter": "active"})
        r.raise_for_status()
        torrents = r.json()
        return {
            "active": len(torrents),
            "downloading": len([t for t in torrents if "download" in t.get("state", "").lower()]),
        }

    # ── requests ───────────────────────────────────────────────────────────────

    async def _get_requests(self, client: httpx.AsyncClient) -> list[RequestItem]:
        """Build the full list of in-progress media requests.

        Fetches the 20 most recent Jellyseerr requests, enriches each with
        Radarr/Sonarr queue and history data, then appends items that were
        added directly in Radarr or Sonarr (i.e. have no Jellyseerr request).
        Results are sorted newest-first by request or activity date.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client.

        Returns
        -------
        list[RequestItem]
            Merged and sorted list of request items from all sources.
        """
        r = await client.get(
            f"{JELLYSEERR_URL}/api/v1/request",
            params={"take": 20, "sort": "added"},
            headers={"X-Api-Key": JELLYSEERR_API_KEY},
        )
        r.raise_for_status()
        js_requests = r.json().get("results", [])

        # Fetch queues and downloader slots in parallel
        radarr_queue, sonarr_queue, sabnzbd_slots, qbit_torrents = await asyncio.gather(
            self._radarr_queue(client),
            self._sonarr_queue(client),
            self._sabnzbd_slots(client),
            self._qbit_torrents(client),
            return_exceptions=True,
        )
        if isinstance(radarr_queue, Exception):
            logger.warning("Radarr queue fetch failed: %s", radarr_queue); radarr_queue = []
        if isinstance(sonarr_queue, Exception):
            logger.warning("Sonarr queue fetch failed: %s", sonarr_queue); sonarr_queue = []
        if isinstance(sabnzbd_slots, Exception):
            logger.warning("SABnzbd slots fetch failed: %s", sabnzbd_slots); sabnzbd_slots = {}
        if isinstance(qbit_torrents, Exception):
            logger.warning("qBittorrent fetch failed: %s", qbit_torrents); qbit_torrents = {}

        # Build Jellyseerr-request items and track which IDs they cover
        results = []
        js_movie_ids: set[int] = set()
        js_series_ids: set[int] = set()

        for req in js_requests:
            item = await self._build_js_item(client, req, radarr_queue, sonarr_queue, sabnzbd_slots, qbit_torrents)
            results.append(item)
            arr_id = req.get("media", {}).get("externalServiceId")
            if arr_id:
                if req.get("type") == "movie":
                    js_movie_ids.add(arr_id)
                else:
                    js_series_ids.add(arr_id)

        # Append items added directly in Radarr/Sonarr
        direct = await self._get_direct_items(
            client, js_movie_ids, js_series_ids, radarr_queue, sonarr_queue, sabnzbd_slots, qbit_torrents
        )
        results.extend(direct)

        results.sort(
            key=lambda item: item.get("requested_at") or (item.get("arr") or {}).get("at") or "",
            reverse=True,
        )

        return results

    async def _build_js_item(
        self,
        client: httpx.AsyncClient,
        req: dict[str, object],
        radarr_queue: list[dict[str, object]],
        sonarr_queue: list[dict[str, object]],
        sabnzbd_slots: dict[str, dict[str, object]],
        qbit_torrents: dict[str, dict[str, object]],
    ) -> RequestItem:
        """Build a normalised RequestItem from a single Jellyseerr request.

        Looks up the corresponding Radarr or Sonarr queue entry and, if absent,
        falls back to per-item history. Download progress is resolved from
        SABnzbd or qBittorrent where a matching slot or torrent exists.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client (used for title lookups when ``arr_id`` is missing).
        req : dict[str, object]
            Raw Jellyseerr request object.
        radarr_queue : list[dict[str, object]]
            Current Radarr download queue records.
        sonarr_queue : list[dict[str, object]]
            Current Sonarr download queue records.
        sabnzbd_slots : dict[str, dict[str, object]]
            SABnzbd queue slots keyed by ``nzo_id``.
        qbit_torrents : dict[str, dict[str, object]]
            qBittorrent torrents keyed by lowercase info-hash.

        Returns
        -------
        RequestItem
            Normalised item with status, download progress, and history
            populated where available.
        """
        media = req.get("media", {})
        media_type = req.get("type", "movie")
        arr_id = media.get("externalServiceId")

        item = {
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
                r = await client.get(
                    f"{JELLYSEERR_URL}/api/v1/{endpoint}/{tmdb_id}",
                    headers={"X-Api-Key": JELLYSEERR_API_KEY},
                )
                if r.status_code == 200:
                    d = r.json()
                    item["title"] = d.get("title") or d.get("name") or item["title"]
            except Exception:
                pass
            return item

        if media_type == "movie":
            queue_item = next((q for q in radarr_queue if q.get("movieId") == arr_id), None)
            if queue_item:
                item["arr"] = self._arr_queue_status(queue_item)
                item["download"] = self._resolve_download(queue_item, sabnzbd_slots, qbit_torrents)
                item["title"] = queue_item.get("movie", {}).get("title") or item["title"]
            else:
                try:
                    detail = await self._radarr_movie(client, arr_id)
                    item["title"] = detail.get("title") or item["title"]
                except Exception:
                    pass
                history = await self._radarr_movie_history(client, arr_id)
                item["arr"] = self._arr_history_status(history, media)
                item["history"] = self._format_history(history[:5])

        elif media_type == "tv":
            queue_items = [q for q in sonarr_queue if q.get("seriesId") == arr_id]
            if queue_items:
                q = queue_items[0]
                item["arr"] = {"status": "downloading", "episodes_queued": len(queue_items), "error": None}
                item["download"] = self._resolve_download(q, sabnzbd_slots, qbit_torrents)
                item["title"] = queue_items[0].get("series", {}).get("title") or item["title"]
            else:
                try:
                    detail = await self._sonarr_series(client, arr_id)
                    item["title"] = detail.get("title") or item["title"]
                except Exception:
                    pass
                history = await self._sonarr_series_history(client, arr_id)
                item["arr"] = self._arr_history_status(history, media)
                item["history"] = self._format_history(history[:5])

        return item

    # ── direct items (Radarr/Sonarr, not via Jellyseerr) ─────────────────────

    async def _get_direct_items(
        self,
        client: httpx.AsyncClient,
        js_movie_ids: set[int],
        js_series_ids: set[int],
        radarr_queue: list[dict[str, object]],
        sonarr_queue: list[dict[str, object]],
        sabnzbd_slots: dict[str, dict[str, object]],
        qbit_torrents: dict[str, dict[str, object]],
    ) -> list[RequestItem]:
        """Fetch items added directly in Radarr/Sonarr that have no Jellyseerr request.

        Combines untracked queue entries (any age) with recent global history
        events (windowed to ``HISTORY_WINDOW_DAYS``) to discover movie and series
        IDs not already covered by ``js_movie_ids`` / ``js_series_ids``.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client.
        js_movie_ids : set[int]
            Radarr movie IDs already accounted for by Jellyseerr requests.
        js_series_ids : set[int]
            Sonarr series IDs already accounted for by Jellyseerr requests.
        radarr_queue : list[dict[str, object]]
            Current Radarr download queue records.
        sonarr_queue : list[dict[str, object]]
            Current Sonarr download queue records.
        sabnzbd_slots : dict[str, dict[str, object]]
            SABnzbd queue slots keyed by ``nzo_id``.
        qbit_torrents : dict[str, dict[str, object]]
            qBittorrent torrents keyed by lowercase info-hash.

        Returns
        -------
        list[RequestItem]
            Items sourced from Radarr (``source="radarr"``) or
            Sonarr (``source="sonarr"``).
        """
        # Fetch global history in parallel to find recent direct activity
        radarr_hist, sonarr_hist = await asyncio.gather(
            self._radarr_recent_history(client),
            self._sonarr_recent_history(client),
            return_exceptions=True,
        )
        if isinstance(radarr_hist, Exception):
            logger.warning("Radarr history fetch failed: %s", radarr_hist); radarr_hist = []
        if isinstance(sonarr_hist, Exception):
            logger.warning("Sonarr history fetch failed: %s", sonarr_hist); sonarr_hist = []

        # Collect untracked IDs from queue (any age) + history (windowed)
        untracked_movie_ids: set[int] = set()
        untracked_series_ids: set[int] = set()

        for q in radarr_queue:
            mid = q.get("movieId")
            if mid and mid not in js_movie_ids:
                untracked_movie_ids.add(mid)

        for q in sonarr_queue:
            sid = q.get("seriesId")
            if sid and sid not in js_series_ids:
                untracked_series_ids.add(sid)

        for event in radarr_hist:
            mid = event.get("movieId")
            if mid and mid not in js_movie_ids and self._is_recent(event.get("date")):
                untracked_movie_ids.add(mid)

        for event in sonarr_hist:
            sid = event.get("seriesId")
            if sid and sid not in js_series_ids and self._is_recent(event.get("date")):
                untracked_series_ids.add(sid)

        if not untracked_movie_ids and not untracked_series_ids:
            return []

        # Fetch details for all untracked IDs in parallel
        movie_ids = list(untracked_movie_ids)
        series_ids = list(untracked_series_ids)

        movie_details, series_details = await asyncio.gather(
            asyncio.gather(*[self._radarr_movie(client, mid) for mid in movie_ids], return_exceptions=True),
            asyncio.gather(*[self._sonarr_series(client, sid) for sid in series_ids], return_exceptions=True),
        )

        results = []

        for i, mid in enumerate(movie_ids):
            detail = movie_details[i] if not isinstance(movie_details[i], Exception) else None
            if not detail:
                continue
            queue_item = next((q for q in radarr_queue if q.get("movieId") == mid), None)
            hist_events = [e for e in radarr_hist if e.get("movieId") == mid]

            item = {
                "id": None,
                "title": detail.get("title", "Unknown"),
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
                item["download"] = self._resolve_download(queue_item, sabnzbd_slots, qbit_torrents)
            elif detail.get("hasFile"):
                item["arr"] = {"status": "imported", "error": None}
                item["history"] = self._format_history(hist_events[:5])
                item["requested_at"] = hist_events[0].get("date") if hist_events else None
            else:
                item["arr"] = self._arr_history_status(hist_events, {})
                item["history"] = self._format_history(hist_events[:5])

            results.append(item)

        for i, sid in enumerate(series_ids):
            detail = series_details[i] if not isinstance(series_details[i], Exception) else None
            if not detail:
                continue
            queue_items = [q for q in sonarr_queue if q.get("seriesId") == sid]
            hist_events = [e for e in sonarr_hist if e.get("seriesId") == sid]
            stats = detail.get("statistics", {})
            ep_total = stats.get("episodeCount", 0)
            ep_have = stats.get("episodeFileCount", 0)

            item = {
                "id": None,
                "title": detail.get("title", "Unknown"),
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
                item["download"] = self._resolve_download(queue_items[0], sabnzbd_slots, qbit_torrents)
            elif ep_have > 0:
                status = "available" if ep_have >= ep_total and ep_total > 0 else "partial"
                item["arr"] = {"status": status, "episodes": f"{ep_have}/{ep_total}", "error": None}
                item["history"] = self._format_history(hist_events[:5])
                item["requested_at"] = hist_events[0].get("date") if hist_events else None
            else:
                item["arr"] = self._arr_history_status(hist_events, {})
                item["history"] = self._format_history(hist_events[:5])

            results.append(item)

        return results

    # ── queue / slot / history fetchers ──────────────────────────────────────

    async def _radarr_queue(self, client: httpx.AsyncClient) -> list[dict[str, object]]:
        """Return the current Radarr download queue (up to 100 records).

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client.

        Returns
        -------
        list[dict[str, object]]
            Raw Radarr queue records with embedded movie details.

        Raises
        ------
        httpx.HTTPStatusError
            On non-2xx response.
        """
        r = await client.get(
            f"{RADARR_URL}/api/v3/queue",
            params={"pageSize": 100, "includeMovie": True},
            headers={"X-Api-Key": RADARR_API_KEY},
        )
        r.raise_for_status()
        return r.json().get("records", [])

    async def _sonarr_queue(self, client: httpx.AsyncClient) -> list[dict[str, object]]:
        """Return the current Sonarr download queue (up to 100 records).

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client.

        Returns
        -------
        list[dict[str, object]]
            Raw Sonarr queue records with embedded series details.

        Raises
        ------
        httpx.HTTPStatusError
            On non-2xx response.
        """
        r = await client.get(
            f"{SONARR_URL}/api/v3/queue",
            params={"pageSize": 100, "includeSeries": True},
            headers={"X-Api-Key": SONARR_API_KEY},
        )
        r.raise_for_status()
        return r.json().get("records", [])

    async def _sabnzbd_slots(self, client: httpx.AsyncClient) -> dict[str, dict[str, object]]:
        """Return the current SABnzbd queue slots keyed by NZO ID.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client.

        Returns
        -------
        dict[str, dict[str, object]]
            Mapping of ``nzo_id`` → raw SABnzbd slot object.

        Raises
        ------
        httpx.HTTPStatusError
            On non-2xx response.
        """
        r = await client.get(
            f"{SABNZBD_URL}/api",
            params={"mode": "queue", "apikey": SABNZBD_API_KEY, "output": "json"},
        )
        r.raise_for_status()
        slots = r.json()["queue"].get("slots", [])
        return {slot["nzo_id"]: slot for slot in slots}

    async def _qbit_torrents(self, client: httpx.AsyncClient) -> dict[str, dict[str, object]]:
        """Return all qBittorrent torrents keyed by lowercase info-hash.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client. A login request is issued to obtain a session
            cookie before fetching torrent data.

        Returns
        -------
        dict[str, dict[str, object]]
            Mapping of lowercase torrent hash → raw qBittorrent torrent object.

        Raises
        ------
        httpx.HTTPStatusError
            On non-2xx response from the torrent-info endpoint.
        """
        await client.post(
            f"{QBITTORRENT_URL}/api/v2/auth/login",
            data={"username": QBITTORRENT_USER, "password": QBITTORRENT_PASS},
        )
        r = await client.get(f"{QBITTORRENT_URL}/api/v2/torrents/info")
        r.raise_for_status()
        return {t["hash"].lower(): t for t in r.json()}

    async def _radarr_movie_history(self, client: httpx.AsyncClient, movie_id: int) -> list[dict[str, object]]:
        """Fetch the event history for a specific Radarr movie.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client.
        movie_id : int
            Radarr internal movie ID.

        Returns
        -------
        list[dict[str, object]]
            History event records, newest first. Returns an empty list on
            non-200 responses rather than raising.
        """
        r = await client.get(
            f"{RADARR_URL}/api/v3/history/movie",
            params={"movieId": movie_id},
            headers={"X-Api-Key": RADARR_API_KEY},
        )
        return r.json() if r.status_code == 200 else []

    async def _sonarr_series_history(self, client: httpx.AsyncClient, series_id: int) -> list[dict[str, object]]:
        """Fetch the event history for a specific Sonarr series.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client.
        series_id : int
            Sonarr internal series ID.

        Returns
        -------
        list[dict[str, object]]
            History event records, newest first. Returns an empty list on
            non-200 responses rather than raising.
        """
        r = await client.get(
            f"{SONARR_URL}/api/v3/history/series",
            params={"seriesId": series_id},
            headers={"X-Api-Key": SONARR_API_KEY},
        )
        return r.json() if r.status_code == 200 else []

    async def _radarr_recent_history(self, client: httpx.AsyncClient) -> list[dict[str, object]]:
        """Fetch the 50 most recent events from the global Radarr history.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client.

        Returns
        -------
        list[dict[str, object]]
            History event records sorted newest-first. Returns an empty list on
            non-200 responses rather than raising.
        """
        r = await client.get(
            f"{RADARR_URL}/api/v3/history",
            params={"pageSize": 50, "sortKey": "date", "sortDir": "desc"},
            headers={"X-Api-Key": RADARR_API_KEY},
        )
        return r.json().get("records", []) if r.status_code == 200 else []

    async def _sonarr_recent_history(self, client: httpx.AsyncClient) -> list[dict[str, object]]:
        """Fetch the 50 most recent events from the global Sonarr history.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client.

        Returns
        -------
        list[dict[str, object]]
            History event records sorted newest-first. Returns an empty list on
            non-200 responses rather than raising.
        """
        r = await client.get(
            f"{SONARR_URL}/api/v3/history",
            params={"pageSize": 50, "sortKey": "date", "sortDir": "desc"},
            headers={"X-Api-Key": SONARR_API_KEY},
        )
        return r.json().get("records", []) if r.status_code == 200 else []

    async def _radarr_movie(self, client: httpx.AsyncClient, movie_id: int) -> dict[str, object]:
        """Fetch full details for a specific Radarr movie.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client.
        movie_id : int
            Radarr internal movie ID.

        Returns
        -------
        dict[str, object]
            Raw Radarr movie object.

        Raises
        ------
        httpx.HTTPStatusError
            On non-2xx response.
        """
        r = await client.get(
            f"{RADARR_URL}/api/v3/movie/{movie_id}",
            headers={"X-Api-Key": RADARR_API_KEY},
        )
        r.raise_for_status()
        return r.json()

    async def _sonarr_series(self, client: httpx.AsyncClient, series_id: int) -> dict[str, object]:
        """Fetch full details for a specific Sonarr series.

        Parameters
        ----------
        client : httpx.AsyncClient
            Shared HTTP client.
        series_id : int
            Sonarr internal series ID.

        Returns
        -------
        dict[str, object]
            Raw Sonarr series object.

        Raises
        ------
        httpx.HTTPStatusError
            On non-2xx response.
        """
        r = await client.get(
            f"{SONARR_URL}/api/v3/series/{series_id}",
            headers={"X-Api-Key": SONARR_API_KEY},
        )
        r.raise_for_status()
        return r.json()

    # ── status helpers ────────────────────────────────────────────────────────

    def _is_recent(self, date_str: str | None) -> bool:
        """Return True if *date_str* falls within the configured history window.

        Parameters
        ----------
        date_str : str or None
            ISO-8601 date string, optionally with a trailing ``Z``. Returns
            ``False`` immediately when ``None`` or unparseable.

        Returns
        -------
        bool
            ``True`` if the date is within ``HISTORY_WINDOW_DAYS`` of now.
        """
        if not date_str:
            return False
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - dt) < timedelta(days=HISTORY_WINDOW_DAYS)
        except ValueError:
            return False

    def _js_status(self, req_status: int | None, media_status: int | None) -> str:
        """Map Jellyseerr request and media status codes to a display string.

        Parameters
        ----------
        req_status : int or None
            Jellyseerr request status code (1=pending, 2=approved, 3=declined).
        media_status : int or None
            Jellyseerr media status code (4=partial, 5=available).

        Returns
        -------
        str
            One of ``"available"``, ``"partial"``, ``"pending"``, ``"approved"``,
            ``"declined"``, or ``"unknown"``.

        Notes
        -----
        ``media_status`` takes precedence over ``req_status`` when set to 4 or 5.
        """
        if media_status == 5: return "available"
        if media_status == 4: return "partial"
        return {1: "pending", 2: "approved", 3: "declined"}.get(req_status, "unknown")

    def _arr_queue_status(self, queue_item: dict[str, object]) -> ArrStatus:
        """Derive an ArrStatus from a Radarr or Sonarr active queue record.

        Parameters
        ----------
        queue_item : dict[str, object]
            A single record from the Radarr/Sonarr ``/queue`` endpoint.

        Returns
        -------
        ArrStatus
            ``status`` is one of ``"downloading"``, ``"warning"``, or ``"error"``.
            ``error`` contains the first status message text when present.
        """
        tracked_status = queue_item.get("trackedDownloadStatus", "Ok")
        messages = queue_item.get("statusMessages", [])
        error = None
        for msg in messages:
            texts = msg.get("messages", [])
            if texts:
                error = "; ".join(texts)
                break
        return {
            "status": "warning" if tracked_status == "Warning" else ("error" if tracked_status == "Error" else "downloading"),
            "error": error,
        }

    def _arr_history_status(self, history: list[dict[str, object]], media: dict[str, object]) -> ArrStatus:
        """Derive an ArrStatus from a Radarr or Sonarr history event list.

        Parameters
        ----------
        history : list[dict[str, object]]
            History events for the item, newest first.
        media : dict[str, object]
            Jellyseerr media object for the item (used to detect ``status=5``).

        Returns
        -------
        ArrStatus
            Derived from the most recent history event. ``status`` is one of
            ``"available"``, ``"searching"``, ``"grabbed"``, ``"failed"``,
            ``"imported"``, ``"ignored"``, or the raw ``eventType`` string.
            Includes ``at`` (event timestamp) when derived from history.
        """
        if media.get("status") == 5:
            return {"status": "available", "error": None}
        if not history:
            return {"status": "searching", "error": None}
        latest = history[0]
        event = latest.get("eventType", "")
        event_map = {
            "grabbed": "grabbed",
            "downloadFailed": "failed",
            "downloadFolderImported": "imported",
            "movieFileImported": "imported",
            "episodeFileImported": "imported",
            "downloadIgnored": "ignored",
            "importFailed": "failed",
        }
        status = event_map.get(event, event)
        error = None
        if status == "failed":
            error = latest.get("data", {}).get("message") or latest.get("sourceTitle", "")
        return {"status": status, "error": error, "at": latest.get("date")}

    def _resolve_download(
        self,
        queue_item: dict[str, object],
        sabnzbd_slots: dict[str, dict[str, object]],
        qbit_torrents: dict[str, dict[str, object]],
    ) -> DownloadInfo:
        """Resolve download progress details for a queued item.

        Matches the queue item's download ID against the SABnzbd slot map and
        the qBittorrent torrent map. Falls back to computing progress from the
        queue item's ``size`` / ``sizeleft`` fields when no client match is found.

        Parameters
        ----------
        queue_item : dict[str, object]
            A single Radarr or Sonarr queue record.
        sabnzbd_slots : dict[str, dict[str, object]]
            SABnzbd queue slots keyed by ``nzo_id``.
        qbit_torrents : dict[str, dict[str, object]]
            qBittorrent torrents keyed by lowercase info-hash.

        Returns
        -------
        DownloadInfo
            Client name, display name, progress percentage, status, ETA, and
            any error message.
        """
        download_id = queue_item.get("downloadId", "")
        download_client = (queue_item.get("downloadClient") or "").lower()

        if "sabnzbd" in download_client and download_id in sabnzbd_slots:
            slot = sabnzbd_slots[download_id]
            return {
                "client": "SABnzbd",
                "name": slot.get("filename", ""),
                "progress": float(slot.get("percentage", 0)),
                "status": slot.get("status", "").lower(),
                "eta": slot.get("timeleft", ""),
                "error": slot.get("fail_message") or None,
            }

        hash_key = download_id.lower()
        if hash_key in qbit_torrents:
            t = qbit_torrents[hash_key]
            return {
                "client": "qBittorrent",
                "name": t.get("name", ""),
                "progress": round(t.get("progress", 0) * 100, 1),
                "status": t.get("state", "").lower(),
                "eta": str(t.get("eta", "")),
                "error": None,
            }

        size = queue_item.get("size", 0)
        sizeleft = queue_item.get("sizeleft", 0)
        progress = round((size - sizeleft) / size * 100, 1) if size > 0 else 0
        return {
            "client": queue_item.get("downloadClient") or "Unknown",
            "name": queue_item.get("title", ""),
            "progress": progress,
            "status": queue_item.get("status", "").lower(),
            "eta": "",
            "error": None,
        }

    def _format_history(self, events: list[dict[str, object]]) -> list[HistoryEvent]:
        """Convert raw arr history events to a simplified format.

        Parameters
        ----------
        events : list[dict[str, object]]
            Raw Radarr or Sonarr history event records.

        Returns
        -------
        list[HistoryEvent]
            Simplified event list. ``error`` is populated for ``downloadFailed``
            and ``importFailed`` event types.
        """
        out = []
        for e in events:
            event_type = e.get("eventType", "")
            error = None
            if event_type in ("downloadFailed", "importFailed"):
                error = e.get("data", {}).get("message") or e.get("sourceTitle", "")
            out.append({
                "event": event_type,
                "at": e.get("date"),
                "source": e.get("sourceTitle", ""),
                "error": error,
            })
        return out
