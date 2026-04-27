"""Demo application — serves the Movieseer dashboard with synthetic data.

No environment variables or downstream services required.
Run with: uvicorn movieseer.demo:app
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

logger = logging.getLogger(__name__)

app = FastAPI()

_TEMPLATE = Path(__file__).parent / "templates" / "index.html"

# ---------------------------------------------------------------------------
# Synthetic data
# ---------------------------------------------------------------------------

_PROWLARR = {
    "total": 5,
    "failing": 0,
    "healthy": 5,
    "issues": [],
    "indexers": [
        {"id": 1, "name": "NZBgeek",      "protocol": "usenet",  "enabled": True, "failing": False, "error": None},
        {"id": 2, "name": "NewzDark",     "protocol": "usenet",  "enabled": True, "failing": False, "error": None},
        {"id": 3, "name": "DrunkenSlug",  "protocol": "usenet",  "enabled": True, "failing": False, "error": None},
        {"id": 4, "name": "1337x",        "protocol": "torrent", "enabled": True, "failing": False, "error": None},
        {"id": 5, "name": "RARBG Mirror", "protocol": "torrent", "enabled": True, "failing": False, "error": None},
    ],
}

_STATUS = {
    "system": {
        "prowlarr": _PROWLARR,
        "sabnzbd": {
            "count": 2,
            "speed": "12.4 MB/s",
            "eta": "0:08:41",
            "paused": False,
            # Keys use Pydantic alias names — that is what the dashboard JS reads
            "slots": [
                {
                    "nzo_id": "SABnzbd001",
                    "filename": "Dune.Part.Two.2024.2160p.BluRay.x265",
                    "percentage": 67.3,
                    "timeleft": "0:04:23",
                    "status": "Downloading",
                },
                {
                    "nzo_id": "SABnzbd002",
                    "filename": "Severance.S02E06.WEB-DL.1080p",
                    "percentage": 12.8,
                    "timeleft": "0:08:41",
                    "status": "Downloading",
                },
            ],
        },
        "qbittorrent": [
            {
                "hash": "a1b2c3d4e5f67890abcdef1234567890abcdef12",
                "name": "The.Bear.S03.1080p.WEB-DL.DD5.1.H.264",
                "state": "downloading",
                "progress": 0.34,
                "eta": 7200,
                "size": 14_123_456_789,
            }
        ],
    },
    "requests": [
        {
            "id": 101,
            "title": "Dune: Part Two",
            "type": "movie",
            "source": "jellyseerr",
            "requested_by": "brendan",
            "requested_at": "2026-04-25T14:32:00+00:00",
            "jellyseerr_status": "Downloading",
            "arr": {"status": "downloading", "error": None, "at": "2026-04-25T15:05:00+00:00"},
            "history": [
                {"event": "grabbed", "at": "2026-04-25T15:05:00+00:00", "source": "radarr", "error": None}
            ],
        },
        {
            "id": 102,
            "title": "Severance",
            "type": "tv",
            "source": "jellyseerr",
            "requested_by": "brendan",
            "requested_at": "2026-04-24T09:10:00+00:00",
            "jellyseerr_status": "Downloading",
            "arr": {
                "status": "downloading",
                "error": None,
                "at": "2026-04-24T09:30:00+00:00",
                "episodes_queued": 3,
            },
            "history": [
                {"event": "grabbed", "at": "2026-04-24T09:30:00+00:00", "source": "sonarr", "error": None}
            ],
        },
        {
            "id": 99,
            "title": "The Brutalist",
            "type": "movie",
            "source": "jellyseerr",
            "requested_by": "brendan",
            "requested_at": "2026-04-20T18:44:00+00:00",
            "jellyseerr_status": "Available",
            "arr": {"status": "imported", "error": None, "at": "2026-04-20T22:15:00+00:00"},
            "history": [
                {"event": "imported", "at": "2026-04-20T22:15:00+00:00", "source": "radarr", "error": None},
                {"event": "grabbed",  "at": "2026-04-20T20:30:00+00:00", "source": "radarr", "error": None},
            ],
        },
        {
            "id": 98,
            "title": "The Bear",
            "type": "tv",
            "source": "sonarr",
            "requested_by": "brendan",
            "requested_at": None,
            "jellyseerr_status": None,
            "arr": {
                "status": "downloading",
                "error": None,
                "at": "2026-04-26T07:20:00+00:00",
                "episodes_queued": 8,
            },
            "history": [
                {"event": "grabbed", "at": "2026-04-26T07:20:00+00:00", "source": "sonarr", "error": None}
            ],
        },
        {
            "id": 95,
            "title": "Conclave",
            "type": "movie",
            "source": "jellyseerr",
            "requested_by": "brendan",
            "requested_at": "2026-04-15T21:00:00+00:00",
            "jellyseerr_status": "Available",
            "arr": {"status": "imported", "error": None, "at": "2026-04-15T23:45:00+00:00"},
            "history": [
                {"event": "imported", "at": "2026-04-15T23:45:00+00:00", "source": "radarr", "error": None},
                {"event": "grabbed",  "at": "2026-04-15T21:20:00+00:00", "source": "radarr", "error": None},
            ],
        },
    ],
}

_CONTAINERS = [
    {"name": "flaresolverr", "status": "running", "uptime": "12d 4h"},
    {"name": "gluetun",      "status": "running", "uptime": "12d 4h"},
    {"name": "jellyfin",     "status": "running", "uptime": "12d 3h"},
    {"name": "jellyseerr",   "status": "running", "uptime": "12d 3h"},
    {"name": "movieseer",    "status": "running", "uptime": "12d 4h"},
    {"name": "ntfy",         "status": "running", "uptime": "12d 4h"},
    {"name": "plex",         "status": "running", "uptime": "12d 3h"},
    {"name": "prowlarr",     "status": "running", "uptime": "11d 22h"},
    {"name": "qbittorrent",  "status": "running", "uptime": "12d 4h"},
    {"name": "radarr",       "status": "running", "uptime": "11d 22h"},
    {"name": "sabnzbd",      "status": "running", "uptime": "12d 4h"},
    {"name": "sonarr",       "status": "running", "uptime": "11d 22h"},
]

_INFRA = {
    "prowlarr": _PROWLARR,
    "sabnzbd_servers": [
        {
            "name": "news.eweka.nl",
            "ssl": True,
            "articles_tried": 284_501,
            "articles_success": 283_748,
            "hit_rate": 0.9974,
        },
        {
            "name": "news.frugalusenet.com",
            "ssl": True,
            "articles_tried": 12_430,
            "articles_success": 11_891,
            "hit_rate": 0.9566,
        },
    ],
}

# Newest-first; reversed on SSE connect to match the real app's behaviour
_EVENTS = [
    {"id": 11, "source": "sonarr",     "event_type": "grabbed",  "title": "The Bear",      "detail": "The Bear S03E01-08 grabbed — [1337x] WEB 1080p",          "at": "2026-04-26T07:20:00+00:00"},
    {"id": 10, "source": "radarr",     "event_type": "grabbed",  "title": "Dune: Part Two", "detail": "Dune: Part Two grabbed — [NZBgeek] BluRay 2160p",         "at": "2026-04-25T15:05:00+00:00"},
    {"id": 9,  "source": "jellyseerr", "event_type": "request",  "title": "Dune: Part Two", "detail": "brendan requested Dune: Part Two",                        "at": "2026-04-25T14:32:00+00:00"},
    {"id": 8,  "source": "sonarr",     "event_type": "grabbed",  "title": "Severance",      "detail": "Severance S02E06 grabbed — [NZBgeek] WEB-DL 1080p",       "at": "2026-04-24T09:30:00+00:00"},
    {"id": 7,  "source": "jellyseerr", "event_type": "request",  "title": "Severance",      "detail": "brendan requested Severance S02",                         "at": "2026-04-24T09:10:00+00:00"},
    {"id": 6,  "source": "radarr",     "event_type": "imported", "title": "The Brutalist",  "detail": "The Brutalist imported successfully",                     "at": "2026-04-20T22:15:00+00:00"},
    {"id": 5,  "source": "radarr",     "event_type": "grabbed",  "title": "The Brutalist",  "detail": "The Brutalist grabbed — [NZBgeek] BluRay 1080p",          "at": "2026-04-20T20:30:00+00:00"},
    {"id": 4,  "source": "jellyseerr", "event_type": "request",  "title": "The Brutalist",  "detail": "brendan requested The Brutalist",                         "at": "2026-04-20T18:44:00+00:00"},
    {"id": 3,  "source": "radarr",     "event_type": "imported", "title": "Conclave",       "detail": "Conclave imported successfully",                          "at": "2026-04-15T23:45:00+00:00"},
    {"id": 2,  "source": "radarr",     "event_type": "grabbed",  "title": "Conclave",       "detail": "Conclave grabbed — [NZBgeek] BluRay 1080p",               "at": "2026-04-15T21:20:00+00:00"},
    {"id": 1,  "source": "jellyseerr", "event_type": "request",  "title": "Conclave",       "detail": "brendan requested Conclave",                              "at": "2026-04-15T21:00:00+00:00"},
]

_SEARCH_RESULTS = {
    "results": [
        {"title": "Dune: Part Two", "type": "movie", "year": "2024", "poster_url": None, "link": "#"},
        {"title": "The Brutalist",  "type": "movie", "year": "2024", "poster_url": None, "link": "#"},
        {"title": "Conclave",       "type": "movie", "year": "2024", "poster_url": None, "link": "#"},
        {"title": "Severance",      "type": "tv",    "year": "2022", "poster_url": None, "link": "#"},
        {"title": "The Bear",       "type": "tv",    "year": "2022", "poster_url": None, "link": "#"},
    ]
}

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
async def dashboard():
    return FileResponse(_TEMPLATE)


@app.get("/api/config")
async def api_config():
    # null values — the frontend's `if (el && url)` guard leaves links as href="#"
    return {k: None for k in [
        "jellyseerr_url", "jellyfin_url", "plex_url",
        "sonarr_url", "radarr_url", "sabnzbd_url",
        "qbittorrent_url", "prowlarr_url",
    ]}


@app.get("/api/status")
async def api_status():
    return _STATUS


@app.get("/api/infra")
async def api_infra():
    return _INFRA


@app.get("/api/containers")
async def api_containers():
    return {"containers": _CONTAINERS}


@app.get("/api/storage")
async def api_storage():
    return {"total_gb": 12.0, "used_gb": 8.3, "free_gb": 3.7}


@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1)):
    return _SEARCH_RESULTS


@app.get("/api/events")
async def api_events(request: Request) -> StreamingResponse:
    async def event_generator():
        for event in reversed(_EVENTS):
            yield f"data: {json.dumps(event)}\n\n"
        while not await request.is_disconnected():
            await asyncio.sleep(15)
            yield ": keep-alive\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# No-op webhooks and actions
# ---------------------------------------------------------------------------


@app.post("/webhook/radarr")
@app.post("/webhook/sonarr")
async def webhooks():
    return {"ok": True}


@app.post("/actions/restart")
@app.post("/actions/rebuild")
@app.post("/actions/shutdown")
@app.post("/actions/sync-libraries")
async def actions():
    return {"ok": True, "demo": True}


@app.post("/actions/container/{name}/stop")
@app.post("/actions/container/{name}/start")
async def container_action(name: str):
    return {"ok": True, "demo": True}
