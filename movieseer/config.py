"""
Configuration module for Movieseer.

All environment variable reads are centralised here. No other module should
call ``os.getenv`` directly — import from this module instead. This ensures
that configuration is always found in one place and that env var names never
drift across files.
"""

import os

# ---------------------------------------------------------------------------
# Jellyseerr
# ---------------------------------------------------------------------------

JELLYSEERR_URL: str = os.getenv("JELLYSEERR_URL", "http://jellyseerr:5055")
JELLYSEERR_API_KEY: str = os.getenv("JELLYSEERR_API_KEY", "")

# ---------------------------------------------------------------------------
# Radarr
# ---------------------------------------------------------------------------

RADARR_URL: str = os.getenv("RADARR_URL", "http://radarr:7878")
RADARR_API_KEY: str = os.getenv("RADARR_API_KEY", "")

# ---------------------------------------------------------------------------
# Sonarr
# ---------------------------------------------------------------------------

SONARR_URL: str = os.getenv("SONARR_URL", "http://sonarr:8989")
SONARR_API_KEY: str = os.getenv("SONARR_API_KEY", "")

# ---------------------------------------------------------------------------
# Prowlarr
# ---------------------------------------------------------------------------

PROWLARR_URL: str = os.getenv("PROWLARR_URL", "http://prowlarr:9696")
PROWLARR_API_KEY: str = os.getenv("PROWLARR_API_KEY", "")

# ---------------------------------------------------------------------------
# SABnzbd
# ---------------------------------------------------------------------------

SABNZBD_URL: str = os.getenv("SABNZBD_URL", "http://sabnzbd:8085")
SABNZBD_API_KEY: str = os.getenv("SABNZBD_API_KEY", "")

# ---------------------------------------------------------------------------
# Jellyfin
# ---------------------------------------------------------------------------

JELLYFIN_URL: str = os.getenv("JELLYFIN_URL", "http://jellyfin:8096")
JELLYFIN_API_KEY: str = os.getenv("JELLYFIN_API_KEY", "")

# ---------------------------------------------------------------------------
# Plex
# ---------------------------------------------------------------------------

PLEX_URL: str = os.getenv("PLEX_URL", "http://plex:32400")
PLEX_TOKEN: str = os.getenv("PLEX_TOKEN", "")


# ---------------------------------------------------------------------------
# External access (browser-facing URLs)
#
# HOST_IP is the Tailscale or local IP used to reach services from a browser.
# The port vars mirror the values in .env and are used by /api/config to build
# the links shown on the dashboard.
# ---------------------------------------------------------------------------

HOST_IP: str = os.getenv("HOST_IP", "localhost")
JELLYFIN_PORT: int = int(os.getenv("JELLYFIN_PORT", "8096"))
PLEX_PORT: int = int(os.getenv("PLEX_PORT", "32400"))
JELLYSEERR_PORT: int = int(os.getenv("JELLYSEERR_PORT", "5055"))
SONARR_PORT: int = int(os.getenv("SONARR_PORT", "8989"))
RADARR_PORT: int = int(os.getenv("RADARR_PORT", "7878"))
PROWLARR_PORT: int = int(os.getenv("PROWLARR_PORT", "9696"))
SABNZBD_PORT: int = int(os.getenv("SABNZBD_PORT", "8085"))

# ---------------------------------------------------------------------------
# Aggregator tuning
# ---------------------------------------------------------------------------

MEDIA_MOUNT: str = os.getenv("MEDIA_MOUNT", "/data")

CACHE_TTL: int = int(os.getenv("CACHE_TTL", "30"))
"""Seconds before the aggregator cache is considered stale."""

HISTORY_WINDOW_DAYS: int = int(os.getenv("HISTORY_WINDOW_DAYS", "7"))
"""How many days back to look when surfacing direct Radarr/Sonarr activity."""

# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------

EVENT_DB_PATH: str = os.getenv("EVENT_DB_PATH", "/var/log/movieseer/events.db")
"""Absolute path for the SQLite event log database."""

EVENT_POLL_INTERVAL: int = int(os.getenv("EVENT_POLL_INTERVAL", "30"))
"""Seconds between event collector poll cycles."""

EVENT_RETENTION_DAYS: int = int(os.getenv("EVENT_RETENTION_DAYS", "7"))
"""How many days of events to retain in the database. Older rows are pruned on
each collector cycle."""

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FILE: str = os.getenv("LOG_FILE", "")
"""Absolute path for the log file. Empty string disables file logging."""

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
