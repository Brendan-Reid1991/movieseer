"""Event log — persistent activity feed for the dashboard.

EventCollector polls Radarr, Sonarr, SABnzbd, and Prowlarr on a timer, writing
new signal events to SQLite via EventStore. New events are broadcast to connected
SSE clients (/api/events) by the caller.
"""

from movieseer.event_log.collector import EventCollector
from movieseer.event_log.db import EventStore
from movieseer.event_log.types import EventSource, EventType, LogEvent

__all__ = ["EventCollector", "EventSource", "EventStore", "EventType", "LogEvent"]
