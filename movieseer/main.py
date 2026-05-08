"""
Movieseer — FastAPI application entry point.

Defines all HTTP routes:
- Dashboard UI (static HTML shell)
- /api/status, /api/config, /api/search, /api/containers, /api/storage, /api/infra
- /api/events (SSE activity log stream)
- /webhook/radarr, /webhook/sonarr
- /actions/restart, /actions/rebuild, /actions/sync-libraries
"""

import asyncio
import json
import logging
import shutil
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from movieseer.aggregator import Aggregator
from movieseer.aggregator.types import InfraStatus
from movieseer.config import (
    EVENT_DB_PATH,
    EVENT_POLL_INTERVAL,
    EVENT_RETENTION_DAYS,
    HOST_IP,
    JELLYFIN_API_KEY,
    JELLYFIN_PORT,
    JELLYFIN_URL,
    JELLYSEERR_API_KEY,
    JELLYSEERR_PORT,
    JELLYSEERR_URL,
    LOG_FILE,
    LOG_LEVEL,
    MEDIA_MOUNT,
    PLEX_PORT,
    PLEX_TOKEN,
    PLEX_URL,
    PROWLARR_PORT,
    QBITTORRENT_PORT,
    RADARR_PORT,
    SABNZBD_PORT,
    SONARR_PORT,
)
from movieseer.docker_manager import (
    list_containers,
    rebuild_all,
    restart_all,
    start_container,
    stop_all,
    stop_container,
)
from movieseer.event_log import EventCollector, EventStore, LogEvent


def _configure_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if LOG_FILE:
        Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5))
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=handlers,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


_configure_logging()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

aggregator = Aggregator()
event_store = EventStore(EVENT_DB_PATH)
event_collector = EventCollector(
    store=event_store,
    radarr=aggregator._radarr,
    sonarr=aggregator._sonarr,
    sabnzbd=aggregator._sabnzbd,
    prowlarr=aggregator._prowlarr,
)

# Server sent event subscriber queues — one per connected client
_sse_subscribers: set[asyncio.Queue[LogEvent]] = set()


def _broadcast(events: list[LogEvent]) -> None:
    """Push new events to all active SSE subscribers."""
    for q in _sse_subscribers:
        for event in events:
            q.put_nowait(event)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await event_store.initialise()
    collector_task = asyncio.create_task(
        event_collector.run_forever(
            interval=EVENT_POLL_INTERVAL,
            broadcast_fn=_broadcast,
            retention_days=EVENT_RETENTION_DAYS,
        )
    )
    try:
        yield
    finally:
        collector_task.cancel()
        try:
            await collector_task
        except asyncio.CancelledError:
            pass
        await aggregator.aclose()


app = FastAPI(lifespan=lifespan)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@app.get("/")
async def dashboard():
    """Serve the static dashboard HTML shell."""
    return FileResponse(Path(__file__).parent / "templates" / "index.html")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@app.get("/api/config")
async def api_config():
    """
    Return browser-facing URLs for all services.

    Constructed from HOST_IP and the port env vars so the dashboard can
    populate its navigation links without hardcoding anything in the HTML.
    """
    base = f"http://{HOST_IP}"
    return {
        "jellyseerr_url": f"{base}:{JELLYSEERR_PORT}",
        "jellyfin_url": f"{base}:{JELLYFIN_PORT}",
        "plex_url": f"{base}:{PLEX_PORT}",
        "sonarr_url": f"{base}:{SONARR_PORT}",
        "radarr_url": f"{base}:{RADARR_PORT}",
        "sabnzbd_url": f"{base}:{SABNZBD_PORT}",
        "qbittorrent_url": f"{base}:{QBITTORRENT_PORT}",
        "prowlarr_url": f"{base}:{PROWLARR_PORT}",
    }


# ---------------------------------------------------------------------------
# Existing endpoints
# ---------------------------------------------------------------------------


@app.get("/api/status")
async def api_status():
    """Return aggregated status from all media services."""
    return await aggregator.get_status()


@app.post("/webhook/radarr")
@app.post("/webhook/radarr")
async def arr_webhook(request: Request):
    """
    Receive Radarr webhook events.

    Invalidates the aggregator cache and dispatches a push notification so
    the dashboard reflects the new state on next poll.
    """
    aggregator.invalidate_cache()
    return {"ok": True}


# ---------------------------------------------------------------------------
# New endpoints
# ---------------------------------------------------------------------------


@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1)):
    """
    Proxy a search query to Jellyseerr and return the top 5 results.

    Each result includes title, type (movie/tv), poster URL, and a deep link
    into Jellyseerr so the user can request the item directly.

    Parameters
    ----------
    q : str
        The search query string.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{JELLYSEERR_URL}/api/v1/search",
            params={"query": q, "page": 1},
            headers={"X-Api-Key": JELLYSEERR_API_KEY},
        )
        response.raise_for_status()

    raw_results = response.json().get("results", [])[:5]
    results = []

    for item in raw_results:
        media_type = item.get("mediaType", "movie")
        tmdb_id = item.get("id")
        poster_path = item.get("posterPath")
        poster_url = f"https://image.tmdb.org/t/p/w92{poster_path}" if poster_path else None

        browser_base = f"http://{HOST_IP}:{JELLYSEERR_PORT}"
        if media_type == "tv":
            title = item.get("name") or item.get("originalName", "Unknown")
            year = (item.get("firstAirDate") or "")[:4]
            jellyseerr_link = f"{browser_base}/tv/{tmdb_id}"
        else:
            title = item.get("title") or item.get("originalTitle", "Unknown")
            year = (item.get("releaseDate") or "")[:4]
            jellyseerr_link = f"{browser_base}/movie/{tmdb_id}"

        results.append(
            {
                "title": title,
                "type": media_type,
                "year": year,
                "poster_url": poster_url,
                "link": jellyseerr_link,
            }
        )

    return {"results": results}


@app.get("/api/containers")
async def api_containers():
    """
    Return the status and uptime of all Docker containers.

    Sourced from the Docker socket. Used by the Service Health section of the
    dashboard. Returns an empty list with an error message if the socket is
    not accessible.
    """
    try:
        containers = list_containers()
        return {"containers": containers}
    except RuntimeError as exc:
        logger.error("Docker socket error: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": str(exc), "containers": []},
        )


@app.post("/actions/restart")
async def action_restart():
    """
    Restart all running containers except Movieseer itself.

    Uses ``docker restart`` via the Docker SDK. Returns the list of container
    names that were restarted.
    """
    try:
        restarted = restart_all()
        logger.info("Restarted containers: %s", restarted)
        return {"ok": True, "restarted": restarted}
    except RuntimeError as exc:
        logger.error("Restart failed: %s", exc)
        return JSONResponse(status_code=503, content={"ok": False, "error": str(exc)})


@app.get("/api/storage")
async def api_storage():
    """Return disk usage for the media storage path."""
    try:
        total, used, free = shutil.disk_usage(MEDIA_MOUNT)
        gb = 1024**3
        return {
            "total_gb": round(total / gb, 1),
            "used_gb": round(used / gb, 1),
            "free_gb": round(free / gb, 1),
        }
    except OSError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})


@app.get("/api/infra")
async def api_infra() -> InfraStatus:
    """
    Return per-indexer status from Prowlarr and per-server hit-rate stats
    from SABnzbd. Used by the Indexers & Servers card on the dashboard.

    Polled independently from /api/status at a slower cadence (60s).
    Individual service failures return {"error": "..."} in place of data.
    """
    prowlarr_result, sabnzbd_result = await asyncio.gather(
        aggregator._prowlarr.status(),
        aggregator._sabnzbd.server_health(),
        return_exceptions=True,
    )
    return InfraStatus(
        prowlarr=prowlarr_result
        if not isinstance(prowlarr_result, Exception)
        else {"error": str(prowlarr_result)},
        sabnzbd_servers=sabnzbd_result
        if not isinstance(sabnzbd_result, Exception)
        else {"error": str(sabnzbd_result)},
    )


@app.post("/actions/rebuild")
async def action_rebuild():
    """
    Pull the latest image for each container (except self), then restart.

    This is a best-effort rebuild: it picks up new images but does not
    force-recreate containers (i.e. env vars and mounts stay as-is).
    Returns the list of container names that were rebuilt.
    """
    try:
        rebuilt = rebuild_all()
        logger.info("Rebuilt containers: %s", rebuilt)
        return {"ok": True, "rebuilt": rebuilt}
    except RuntimeError as exc:
        logger.error("Rebuild failed: %s", exc)
        return JSONResponse(status_code=503, content={"ok": False, "error": str(exc)})


@app.post("/actions/shutdown")
async def action_shutdown():
    """
    Stop all containers, with Movieseer last.

    Returns immediately. The shutdown runs in the background after a short
    delay so the response has time to flush before the process exits.
    """

    async def _delayed_stop():
        await asyncio.sleep(1)
        await asyncio.to_thread(stop_all)

    _ = asyncio.create_task(_delayed_stop())
    return {"ok": True}


@app.post("/actions/container/{name}/stop")
async def action_container_stop(name: str):
    """Stop a single container by name."""
    try:
        await asyncio.to_thread(stop_container, name)
        return {"ok": True}
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(exc)})
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(exc)})


@app.post("/actions/container/{name}/start")
async def action_container_start(name: str):
    """Start a single stopped container by name."""
    try:
        await asyncio.to_thread(start_container, name)
        return {"ok": True}
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(exc)})
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# SSE event stream
# ---------------------------------------------------------------------------


@app.get("/api/events")
async def api_events(request: Request) -> StreamingResponse:
    """
    Server-Sent Events stream for the activity log.

    On connect, the last 25 stored events are flushed immediately (oldest
    first) so the feed is pre-populated without waiting for the next poll
    cycle. After that, new events are pushed as they arrive from the
    collector.
    """

    async def event_generator():
        q: asyncio.Queue[LogEvent] = asyncio.Queue()
        _sse_subscribers.add(q)
        try:
            history = await event_store.recent(limit=25)
            for event in reversed(history):
                yield f"data: {json.dumps(event)}\n\n"

            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            _sse_subscribers.discard(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Sync libraries
# ---------------------------------------------------------------------------


async def _emit(source: str, event_type: str, detail: str) -> None:
    """Write a single event to the store and broadcast it to SSE subscribers."""
    events = await event_store.insert(
        [
            LogEvent(
                id=0,
                source=source,
                event_type=event_type,
                title="Library Sync",
                detail=detail,
                at=datetime.now(UTC).isoformat(),
            )
        ]
    )
    _broadcast(events)


async def _sync_jellyfin() -> None:
    try:
        await _emit("jellyfin", "sync_started", "Jellyfin library refresh started")

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{JELLYFIN_URL}/Library/Refresh",
                headers={"X-Emby-Token": JELLYFIN_API_KEY},
            )
            r.raise_for_status()
        logger.info("Jellyfin library refresh triggered")

        async with httpx.AsyncClient(timeout=10.0) as client:
            for _ in range(90):
                await asyncio.sleep(10)
                r = await client.get(
                    f"{JELLYFIN_URL}/ScheduledTasks",
                    headers={"X-Emby-Token": JELLYFIN_API_KEY},
                )
                r.raise_for_status()
                scan_task = next((t for t in r.json() if t.get("Key") == "RefreshLibrary"), None)
                if scan_task is not None and scan_task.get("State") == "Idle":
                    break

        await _emit("jellyfin", "sync_complete", "Jellyfin library refresh complete")
        logger.info("Jellyfin library refresh complete")
    except Exception as exc:
        logger.exception("Jellyfin sync failed")
        await _emit("jellyfin", "failed", f"Jellyfin sync failed — {exc}")
        raise


async def _sync_plex() -> None:
    try:
        await _emit("plex", "sync_started", "Plex library refresh started")
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{PLEX_URL}/library/sections/all/refresh",
                headers={"X-Plex-Token": PLEX_TOKEN},
            )
            r.raise_for_status()
        logger.info("Plex library refresh triggered")

        async with httpx.AsyncClient(timeout=10.0) as client:
            for _ in range(90):
                await asyncio.sleep(10)
                r = await client.get(
                    f"{PLEX_URL}/library/sections",
                    headers={"X-Plex-Token": PLEX_TOKEN, "Accept": "application/json"},
                )
                r.raise_for_status()
                sections = r.json().get("MediaContainer", {}).get("Directory", [])
                if not any(s.get("refreshing") for s in sections):
                    break

        await _emit("plex", "sync_complete", "Plex library refresh complete")
        logger.info("Plex library refresh complete")
    except Exception as exc:
        logger.exception("Plex sync failed")
        await _emit("plex", "failed", f"Plex sync failed — {exc}")
        raise


async def _run_library_sync() -> None:
    try:
        await asyncio.gather(_sync_jellyfin(), _sync_plex())
    except Exception:
        return

    try:
        await _emit("jellyseerr", "sync_started", "Jellyseerr library sync started")
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{JELLYSEERR_URL}/api/v1/settings/jellyfin/sync",
                json={"start": True},
                headers={"X-Api-Key": JELLYSEERR_API_KEY},
            )
            r.raise_for_status()
        logger.info("Jellyseerr library sync triggered")

        async with httpx.AsyncClient(timeout=10.0) as client:
            for _ in range(60):
                await asyncio.sleep(10)
                r = await client.get(
                    f"{JELLYSEERR_URL}/api/v1/settings/jellyfin/sync",
                    headers={"X-Api-Key": JELLYSEERR_API_KEY},
                )
                r.raise_for_status()
                if not r.json().get("running", False):
                    break

        await _emit("jellyseerr", "sync_complete", "Jellyseerr library sync complete")
        logger.info("Jellyseerr library sync complete")
    except Exception as exc:
        logger.exception("Jellyseerr sync failed")
        await _emit("jellyseerr", "failed", f"Jellyseerr sync failed — {exc}")


@app.post("/actions/sync-libraries")
async def action_sync_libraries():
    """
    Kick off a Jellyfin → Jellyseerr library sync in the background.

    Returns immediately. Progress and completion are delivered via the SSE
    event stream (/api/events) as sync_started / sync_complete / failed events.
    """
    _ = asyncio.create_task(_run_library_sync())
    return {"ok": True}
