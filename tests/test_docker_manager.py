"""
Tests for docker_manager.py.

Docker socket operations (list_containers, restart_all, rebuild_all) require
a live socket and are integration concerns. This file covers the pure helper
logic that can be tested in isolation.
"""

from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

import pytest

from movieseer.docker_manager import (
    _format_uptime,
    list_containers,
    restart_all,
    SELF_NAME,
)


class TestFormatUptime:
    """_format_uptime converts Docker StartedAt timestamps to human-readable strings."""

    def _ts(self, delta: timedelta) -> str:
        """Return an ISO timestamp offset from now by ``delta``."""
        dt = datetime.now(timezone.utc) - delta
        # Docker uses nanosecond precision; simulate with microseconds
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    def test_days_and_hours(self):
        ts = self._ts(timedelta(days=3, hours=2))
        assert _format_uptime(ts) == "3d 2h"

    def test_hours_and_minutes(self):
        ts = self._ts(timedelta(hours=5, minutes=30))
        assert _format_uptime(ts) == "5h 30m"

    def test_minutes_only(self):
        ts = self._ts(timedelta(minutes=45))
        assert _format_uptime(ts) == "45m"

    def test_less_than_one_minute(self):
        ts = self._ts(timedelta(seconds=30))
        assert _format_uptime(ts) == "<1m"

    def test_empty_string_returns_unknown(self):
        assert _format_uptime("") == "unknown"

    def test_none_returns_unknown(self):
        assert _format_uptime(None) == "unknown"

    def test_invalid_string_returns_unknown(self):
        assert _format_uptime("not-a-timestamp") == "unknown"


class TestListContainers:
    """list_containers returns sorted container info from the Docker SDK."""

    def _make_container(self, name: str, status: str, started_at: str) -> MagicMock:
        container = MagicMock()
        container.name = name
        container.status = status
        container.attrs = {"State": {"StartedAt": started_at}}
        container.reload = MagicMock()
        return container

    def test_containers_sorted_alphabetically(self):
        ts = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        ) + "Z"
        containers = [
            self._make_container("zebra", "running", ts),
            self._make_container("alpha", "running", ts),
        ]
        mock_client = MagicMock()
        mock_client.containers.list.return_value = containers

        with patch("movieseer.docker_manager._client", return_value=mock_client):
            result = list_containers()

        assert result[0]["name"] == "alpha"
        assert result[1]["name"] == "zebra"

    def test_stopped_container_uptime_shows_status(self):
        containers = [self._make_container("myapp", "exited", "")]
        mock_client = MagicMock()
        mock_client.containers.list.return_value = containers

        with patch("movieseer.docker_manager._client", return_value=mock_client):
            result = list_containers()

        assert result[0]["status"] == "exited"
        assert result[0]["uptime"] == "exited"

    def test_running_container_has_uptime_string(self):
        ts = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        ) + "Z"
        containers = [self._make_container("sonarr", "running", ts)]
        mock_client = MagicMock()
        mock_client.containers.list.return_value = containers

        with patch("movieseer.docker_manager._client", return_value=mock_client):
            result = list_containers()

        assert result[0]["uptime"] == "2h 0m"


class TestRestartAll:
    """restart_all skips self and restarts all other running containers."""

    def _make_container(self, name: str) -> MagicMock:
        c = MagicMock()
        c.name = name
        return c

    def test_self_is_excluded(self):
        containers = [
            self._make_container(SELF_NAME),
            self._make_container("sonarr"),
        ]
        mock_client = MagicMock()
        mock_client.containers.list.return_value = containers

        with patch("movieseer.docker_manager._client", return_value=mock_client):
            restarted = restart_all()

        assert SELF_NAME not in restarted
        assert "sonarr" in restarted

    def test_all_other_containers_restarted(self):
        containers = [self._make_container(n) for n in ["radarr", "sonarr", "jellyfin"]]
        mock_client = MagicMock()
        mock_client.containers.list.return_value = containers

        with patch("movieseer.docker_manager._client", return_value=mock_client):
            restarted = restart_all()

        assert set(restarted) == {"radarr", "sonarr", "jellyfin"}
        for c in containers:
            c.restart.assert_called_once()
