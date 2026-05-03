"""Notifier — dispatches push notifications to ntfy from incoming Radarr/Sonarr webhooks.

Radarr and Sonarr are configured to POST to /webhook/radarr and /webhook/sonarr.
Each payload is parsed, formatted, and forwarded to the ntfy instance as a push
notification.
"""

from movieseer.notifier.handlers import handle_radarr, handle_sonarr

__all__ = ["handle_radarr", "handle_sonarr"]
