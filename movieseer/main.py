"""
Movieseer — FastAPI application entry point.

Defines all HTTP routes:
- Dashboard UI (static HTML shell)
- Existing: /api/status, /webhook/radarr, /webhook/sonarr
- New: /api/config, /api/search, /api/containers, /actions/restart, /actions/rebuild
"""

import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from movieseer.aggregator import Aggregator
from movieseer.config import (
    HOST_IP,
    JELLYFIN_PORT,
    JELLYSEERR_API_KEY,
    JELLYSEERR_PORT,
    JELLYSEERR_URL,
    MEDIA_MOUNT,
    QBITTORRENT_PORT,
    RADARR_PORT,
    SABNZBD_PORT,
    SONARR_PORT,
)
from movieseer.docker_manager import list_containers, rebuild_all, restart_all
from movieseer.notifier import handle_radarr, handle_sonarr

logger = logging.getLogger(__name__)

aggregator = Aggregator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
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
        "sonarr_url": f"{base}:{SONARR_PORT}",
        "radarr_url": f"{base}:{RADARR_PORT}",
        "sabnzbd_url": f"{base}:{SABNZBD_PORT}",
        "qbittorrent_url": f"{base}:{QBITTORRENT_PORT}",
    }


# ---------------------------------------------------------------------------
# Existing endpoints
# ---------------------------------------------------------------------------


@app.get("/api/status")
async def api_status():
    """Return aggregated status from all media services."""
    return await aggregator.get_status()


@app.post("/webhook/radarr")
async def radarr_webhook(request: Request):
    """
    Receive Radarr webhook events.

    Invalidates the aggregator cache and dispatches a push notification so
    the dashboard reflects the new state on next poll.
    """
    payload = await request.json()
    aggregator.invalidate_cache()
    await handle_radarr(payload)
    return {"ok": True}


@app.post("/webhook/sonarr")
async def sonarr_webhook(request: Request):
    """
    Receive Sonarr webhook events.

    Invalidates the aggregator cache and dispatches a push notification so
    the dashboard reflects the new state on next poll.
    """
    payload = await request.json()
    aggregator.invalidate_cache()
    await handle_sonarr(payload)
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
        poster_url = (
            f"https://image.tmdb.org/t/p/w92{poster_path}" if poster_path else None
        )

        if media_type == "tv":
            title = item.get("name") or item.get("originalName", "Unknown")
            year = (item.get("firstAirDate") or "")[:4]
            jellyseerr_link = f"{JELLYSEERR_URL}/tv/{tmdb_id}"
        else:
            title = item.get("title") or item.get("originalTitle", "Unknown")
            year = (item.get("releaseDate") or "")[:4]
            jellyseerr_link = f"{JELLYSEERR_URL}/movie/{tmdb_id}"

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
