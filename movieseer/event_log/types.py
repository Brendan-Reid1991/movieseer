"""Types for the Movieseer event log."""

from __future__ import annotations

from typing import Literal, TypedDict

EventSource = Literal["radarr", "sonarr", "sabnzbd", "prowlarr", "jellyseerr", "jellyfin", "plex"]

EventType = Literal[
    "grabbed",  # Radarr/Sonarr: grabbed a release and sent to download client
    "imported",  # Radarr/Sonarr: download complete, file imported to library
    "failed",  # Radarr/Sonarr/SABnzbd: download or import failed
    "completed",  # SABnzbd: job finished successfully
    "request",  # Jellyseerr: new media request submitted
    "indexer_failing",  # Prowlarr: indexer newly entered failing state
    "indexer_recovered",  # Prowlarr: indexer recovered from failing state
    "sync_started",  # Jellyfin/Plex/Jellyseerr: library sync initiated
    "sync_complete",  # Jellyfin/Plex/Jellyseerr: library sync finished
]


class LogEvent(TypedDict):
    """A single activity log entry."""

    id: int  # SQLite autoincrement; 0 when not yet persisted
    source: EventSource
    event_type: EventType
    title: str  # media title, indexer name, etc.
    detail: str  # pre-formatted human-readable one-liner
    at: str  # ISO 8601 — when the event occurred in the source system
