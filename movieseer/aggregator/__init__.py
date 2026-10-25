"""Aggregator — polls all downstream services and returns a merged status snapshot.

Exposes a single Aggregator class that fans out to Jellyseerr, Radarr, Sonarr,
Prowlarr, SABnzbd, and qBittorrent. Results are cached and served via /api/status.
"""

from movieseer.aggregator.aggregator import Aggregator

__all__ = ["Aggregator"]
