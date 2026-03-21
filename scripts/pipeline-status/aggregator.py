import asyncio
import httpx
import os
import time
from datetime import datetime, timezone, timedelta

JELLYSEERR_URL = os.getenv("JELLYSEERR_URL", "http://jellyseerr:5055")
JELLYSEERR_API_KEY = os.getenv("JELLYSEERR_API_KEY", "")
RADARR_URL = os.getenv("RADARR_URL", "http://radarr:7878")
RADARR_API_KEY = os.getenv("RADARR_API_KEY", "")
SONARR_URL = os.getenv("SONARR_URL", "http://sonarr:8989")
SONARR_API_KEY = os.getenv("SONARR_API_KEY", "")
PROWLARR_URL = os.getenv("PROWLARR_URL", "http://prowlarr:9696")
PROWLARR_API_KEY = os.getenv("PROWLARR_API_KEY", "")
SABNZBD_URL = os.getenv("SABNZBD_URL", "http://sabnzbd:8080")
SABNZBD_API_KEY = os.getenv("SABNZBD_API_KEY", "")
QBITTORRENT_URL = os.getenv("QBITTORRENT_URL", "http://gluetun:8080")
QBITTORRENT_USER = os.getenv("QBITTORRENT_USER", "")
QBITTORRENT_PASS = os.getenv("QBITTORRENT_PASS", "")

CACHE_TTL = 30
HISTORY_WINDOW_DAYS = 7


class Aggregator:
    def __init__(self):
        self._cache = None
        self._cache_time = 0.0

    def invalidate_cache(self):
        self._cache_time = 0.0

    async def get_status(self) -> dict:
        now = time.monotonic()
        if self._cache and (now - self._cache_time) < CACHE_TTL:
            return self._cache

        async with httpx.AsyncClient(timeout=10.0) as client:
            system, requests = await asyncio.gather(
                self._get_system(client),
                self._get_requests(client),
                return_exceptions=True,
            )

        result = {
            "system": system if not isinstance(system, Exception) else {"error": str(system)},
            "requests": requests if not isinstance(requests, Exception) else [],
        }
        self._cache = result
        self._cache_time = now
        return result

    # ── system status ─────────────────────────────────────────────────────────

    async def _get_system(self, client: httpx.AsyncClient) -> dict:
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

    async def _prowlarr_status(self, client: httpx.AsyncClient) -> dict:
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

    async def _sabnzbd_summary(self, client: httpx.AsyncClient) -> dict:
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
        }

    async def _qbit_summary(self, client: httpx.AsyncClient) -> dict:
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

    async def _get_requests(self, client: httpx.AsyncClient) -> list:
        r = await client.get(
            f"{JELLYSEERR_URL}/api/v1/request",
            params={"take": 20, "sort": "added", "order": "desc"},
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
        if isinstance(radarr_queue, Exception): radarr_queue = []
        if isinstance(sonarr_queue, Exception): sonarr_queue = []
        if isinstance(sabnzbd_slots, Exception): sabnzbd_slots = {}
        if isinstance(qbit_torrents, Exception): qbit_torrents = {}

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

        return results

    async def _build_js_item(self, client, req, radarr_queue, sonarr_queue, sabnzbd_slots, qbit_torrents) -> dict:
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
            return item

        if media_type == "movie":
            queue_item = next((q for q in radarr_queue if q.get("movieId") == arr_id), None)
            if queue_item:
                item["arr"] = self._arr_queue_status(queue_item)
                item["download"] = self._resolve_download(queue_item, sabnzbd_slots, qbit_torrents)
            else:
                history = await self._radarr_movie_history(client, arr_id)
                item["arr"] = self._arr_history_status(history, media)
                item["history"] = self._format_history(history[:5])

        elif media_type == "tv":
            queue_items = [q for q in sonarr_queue if q.get("seriesId") == arr_id]
            if queue_items:
                q = queue_items[0]
                item["arr"] = {"status": "downloading", "episodes_queued": len(queue_items), "error": None}
                item["download"] = self._resolve_download(q, sabnzbd_slots, qbit_torrents)
            else:
                history = await self._sonarr_series_history(client, arr_id)
                item["arr"] = self._arr_history_status(history, media)
                item["history"] = self._format_history(history[:5])

        return item

    # ── direct items (Radarr/Sonarr, not via Jellyseerr) ─────────────────────

    async def _get_direct_items(
        self, client, js_movie_ids, js_series_ids, radarr_queue, sonarr_queue, sabnzbd_slots, qbit_torrents
    ) -> list:
        # Fetch global history in parallel to find recent direct activity
        radarr_hist, sonarr_hist = await asyncio.gather(
            self._radarr_recent_history(client),
            self._sonarr_recent_history(client),
            return_exceptions=True,
        )
        if isinstance(radarr_hist, Exception): radarr_hist = []
        if isinstance(sonarr_hist, Exception): sonarr_hist = []

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
            else:
                item["arr"] = self._arr_history_status(hist_events, {})
                item["history"] = self._format_history(hist_events[:5])

            results.append(item)

        return results

    # ── queue / slot / history fetchers ──────────────────────────────────────

    async def _radarr_queue(self, client: httpx.AsyncClient) -> list:
        r = await client.get(
            f"{RADARR_URL}/api/v3/queue",
            params={"pageSize": 100, "includeMovie": True},
            headers={"X-Api-Key": RADARR_API_KEY},
        )
        r.raise_for_status()
        return r.json().get("records", [])

    async def _sonarr_queue(self, client: httpx.AsyncClient) -> list:
        r = await client.get(
            f"{SONARR_URL}/api/v3/queue",
            params={"pageSize": 100, "includeSeries": True},
            headers={"X-Api-Key": SONARR_API_KEY},
        )
        r.raise_for_status()
        return r.json().get("records", [])

    async def _sabnzbd_slots(self, client: httpx.AsyncClient) -> dict:
        r = await client.get(
            f"{SABNZBD_URL}/api",
            params={"mode": "queue", "apikey": SABNZBD_API_KEY, "output": "json"},
        )
        r.raise_for_status()
        slots = r.json()["queue"].get("slots", [])
        return {slot["nzo_id"]: slot for slot in slots}

    async def _qbit_torrents(self, client: httpx.AsyncClient) -> dict:
        await client.post(
            f"{QBITTORRENT_URL}/api/v2/auth/login",
            data={"username": QBITTORRENT_USER, "password": QBITTORRENT_PASS},
        )
        r = await client.get(f"{QBITTORRENT_URL}/api/v2/torrents/info")
        r.raise_for_status()
        return {t["hash"].lower(): t for t in r.json()}

    async def _radarr_movie_history(self, client: httpx.AsyncClient, movie_id: int) -> list:
        r = await client.get(
            f"{RADARR_URL}/api/v3/history/movie",
            params={"movieId": movie_id},
            headers={"X-Api-Key": RADARR_API_KEY},
        )
        return r.json() if r.status_code == 200 else []

    async def _sonarr_series_history(self, client: httpx.AsyncClient, series_id: int) -> list:
        r = await client.get(
            f"{SONARR_URL}/api/v3/history/series",
            params={"seriesId": series_id},
            headers={"X-Api-Key": SONARR_API_KEY},
        )
        return r.json() if r.status_code == 200 else []

    async def _radarr_recent_history(self, client: httpx.AsyncClient) -> list:
        r = await client.get(
            f"{RADARR_URL}/api/v3/history",
            params={"pageSize": 50, "sortKey": "date", "sortDir": "desc"},
            headers={"X-Api-Key": RADARR_API_KEY},
        )
        return r.json().get("records", []) if r.status_code == 200 else []

    async def _sonarr_recent_history(self, client: httpx.AsyncClient) -> list:
        r = await client.get(
            f"{SONARR_URL}/api/v3/history",
            params={"pageSize": 50, "sortKey": "date", "sortDir": "desc"},
            headers={"X-Api-Key": SONARR_API_KEY},
        )
        return r.json().get("records", []) if r.status_code == 200 else []

    async def _radarr_movie(self, client: httpx.AsyncClient, movie_id: int) -> dict:
        r = await client.get(
            f"{RADARR_URL}/api/v3/movie/{movie_id}",
            headers={"X-Api-Key": RADARR_API_KEY},
        )
        r.raise_for_status()
        return r.json()

    async def _sonarr_series(self, client: httpx.AsyncClient, series_id: int) -> dict:
        r = await client.get(
            f"{SONARR_URL}/api/v3/series/{series_id}",
            headers={"X-Api-Key": SONARR_API_KEY},
        )
        r.raise_for_status()
        return r.json()

    # ── status helpers ────────────────────────────────────────────────────────

    def _is_recent(self, date_str: str) -> bool:
        if not date_str:
            return False
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - dt) < timedelta(days=HISTORY_WINDOW_DAYS)
        except ValueError:
            return False

    def _js_status(self, req_status: int, media_status: int) -> str:
        if media_status == 5: return "available"
        if media_status == 4: return "partial"
        return {1: "pending", 2: "approved", 3: "declined"}.get(req_status, "unknown")

    def _arr_queue_status(self, queue_item: dict) -> dict:
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

    def _arr_history_status(self, history: list, media: dict) -> dict:
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

    def _resolve_download(self, queue_item: dict, sabnzbd_slots: dict, qbit_torrents: dict) -> dict:
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

    def _format_history(self, events: list) -> list:
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
