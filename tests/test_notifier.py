"""
Tests for notifier.py.

Verifies that event handlers dispatch correctly without making real HTTP calls.
Unknown or missing event types should be handled silently — notifier must never
raise an exception that would cause a webhook endpoint to return a 500.
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture()
def mock_send():
    """Patch the internal _send coroutine so no HTTP requests are made."""
    with patch("movieseer.notifier._send", new_callable=AsyncMock) as m:
        yield m


class TestHandleRadarr:
    """notifier.handle_radarr dispatches ntfy notifications for Radarr events."""

    @pytest.mark.asyncio
    async def test_grab_event_sends_notification(self, mock_send):
        from movieseer.notifier import handle_radarr
        payload = {
            "eventType": "Grab",
            "movie": {"title": "Dune", "year": 2021},
            "release": {"indexer": "NZBGeek", "quality": "Remux-1080p"},
        }
        await handle_radarr(payload)
        mock_send.assert_awaited_once()
        _, kwargs_title = mock_send.call_args[0][0], mock_send.call_args[0][1]
        assert "Dune" in kwargs_title

    @pytest.mark.asyncio
    async def test_download_event_sends_notification(self, mock_send):
        from movieseer.notifier import handle_radarr
        payload = {"eventType": "Download", "movie": {"title": "Sinners", "year": 2025}}
        await handle_radarr(payload)
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_event_sends_no_notification(self, mock_send):
        from movieseer.notifier import handle_radarr
        await handle_radarr({"eventType": "SomeNewEvent", "movie": {"title": "X", "year": 2025}})
        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_event_type_does_not_raise(self, mock_send):
        from movieseer.notifier import handle_radarr
        await handle_radarr({})  # No eventType key — must not raise


class TestHandleSonarr:
    """notifier.handle_sonarr dispatches ntfy notifications for Sonarr events."""

    @pytest.mark.asyncio
    async def test_grab_event_sends_notification(self, mock_send):
        from movieseer.notifier import handle_sonarr
        payload = {
            "eventType": "Grab",
            "series": {"title": "The Bear"},
            "episodes": [{"seasonNumber": 4, "episodeNumber": 1}],
            "release": {"indexer": "NZBGeek"},
        }
        await handle_sonarr(payload)
        mock_send.assert_awaited_once()
        title_arg = mock_send.call_args[0][1]
        assert "The Bear" in title_arg

    @pytest.mark.asyncio
    async def test_episode_label_formatted_correctly(self, mock_send):
        from movieseer.notifier import handle_sonarr
        payload = {
            "eventType": "Grab",
            "series": {"title": "Severance"},
            "episodes": [{"seasonNumber": 2, "episodeNumber": 7}],
            "release": {},
        }
        await handle_sonarr(payload)
        title_arg = mock_send.call_args[0][1]
        assert "S02E07" in title_arg

    @pytest.mark.asyncio
    async def test_unknown_event_sends_no_notification(self, mock_send):
        from movieseer.notifier import handle_sonarr
        await handle_sonarr({"eventType": "SomeFutureEvent", "series": {"title": "X"}, "episodes": []})
        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_event_type_does_not_raise(self, mock_send):
        from movieseer.notifier import handle_sonarr
        await handle_sonarr({})
