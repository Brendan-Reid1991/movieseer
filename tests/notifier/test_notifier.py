"""
Tests for the notifier package.

Patches _send_message in webhooks.py so no real HTTP calls are made.
Tests verify dispatch, label formatting, and error propagation for
both Radarr and Sonarr events.
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture()
def mock_send():
    """Patch _send_message so no ntfy HTTP requests are made."""
    with patch("movieseer.notifier.webhooks._send_message", new_callable=AsyncMock) as m:
        yield m


# ── TestHandleRadarr ──────────────────────────────────────────────────────────


class TestHandleRadarr:
    """handle_radarr dispatches the correct notification for each Radarr event."""

    async def test_grab_event_dispatches(self, mock_send):
        from movieseer.notifier import handle_radarr

        payload = {
            "eventType": "Grab",
            "movie": {"title": "Dune", "year": 2021},
            "release": {"indexer": "NZBGeek", "quality": "Remux-1080p"},
        }
        await handle_radarr(payload)
        mock_send.assert_awaited_once()

    async def test_grab_title_in_notification(self, mock_send):
        from movieseer.notifier import handle_radarr

        payload = {
            "eventType": "Grab",
            "movie": {"title": "Dune", "year": 2021},
            "release": {"indexer": "NZBGeek", "quality": "Remux-1080p"},
        }
        await handle_radarr(payload)
        title_arg = mock_send.call_args[0][1]
        assert "Dune" in title_arg

    async def test_download_event_dispatches(self, mock_send):
        from movieseer.notifier import handle_radarr

        payload = {"eventType": "Download", "movie": {"title": "Sinners", "year": 2025}}
        await handle_radarr(payload)
        mock_send.assert_awaited_once()

    async def test_unknown_event_raises_value_error(self, mock_send):
        from movieseer.notifier import handle_radarr

        with pytest.raises(ValueError, match="Unknown event type"):
            await handle_radarr(
                {"eventType": "SomeNewEvent", "movie": {"title": "X", "year": 2025}}
            )

    async def test_missing_event_type_raises_value_error(self, mock_send):
        from movieseer.notifier import handle_radarr

        with pytest.raises(ValueError, match="Unknown event type"):
            await handle_radarr({})

    async def test_download_failure_event_dispatches(self, mock_send):
        from movieseer.notifier import handle_radarr

        payload = {
            "eventType": "DownloadFailure",
            "movie": {"title": "Alien", "year": 1979},
            "message": "Download timed out",
        }
        await handle_radarr(payload)
        mock_send.assert_awaited_once()


# ── TestHandleSonarr ──────────────────────────────────────────────────────────


class TestHandleSonarr:
    """handle_sonarr dispatches the correct notification for each Sonarr event."""

    async def test_grab_event_dispatches(self, mock_send):
        from movieseer.notifier import handle_sonarr

        payload = {
            "eventType": "Grab",
            "series": {"title": "The Bear"},
            "episodes": [{"seasonNumber": 4, "episodeNumber": 1}],
            "release": {"indexer": "NZBGeek"},
        }
        await handle_sonarr(payload)
        mock_send.assert_awaited_once()

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

    async def test_series_title_in_notification(self, mock_send):
        from movieseer.notifier import handle_sonarr

        payload = {
            "eventType": "Grab",
            "series": {"title": "The Bear"},
            "episodes": [{"seasonNumber": 4, "episodeNumber": 1}],
            "release": {},
        }
        await handle_sonarr(payload)
        title_arg = mock_send.call_args[0][1]
        assert "The Bear" in title_arg

    async def test_unknown_event_raises_value_error(self, mock_send):
        from movieseer.notifier import handle_sonarr

        with pytest.raises(ValueError, match="Unknown event type"):
            await handle_sonarr(
                {
                    "eventType": "SomeFutureEvent",
                    "series": {"title": "X"},
                    "episodes": [],
                }
            )

    async def test_missing_event_type_raises_value_error(self, mock_send):
        from movieseer.notifier import handle_sonarr

        with pytest.raises(ValueError, match="Unknown event type"):
            await handle_sonarr({})


# ── TestLabeller ──────────────────────────────────────────────────────────────


class TestLabeller:
    """handlers.labeller formats media labels from webhook payloads."""

    def test_radarr_label_includes_title_and_year(self):
        from movieseer.notifier.handlers import labeller

        payload = {"movie": {"title": "Dune", "year": 2021}}
        assert labeller(payload, "radarr") == "Dune (2021)"

    def test_radarr_label_omits_year_when_zero(self):
        from movieseer.notifier.handlers import labeller

        payload = {"movie": {"title": "Dune", "year": 0}}
        assert labeller(payload, "radarr") == "Dune"

    def test_sonarr_label_with_episode(self):
        from movieseer.notifier.handlers import labeller

        payload = {
            "series": {"title": "Severance"},
            "episodes": [{"seasonNumber": 2, "episodeNumber": 7}],
        }
        assert labeller(payload, "sonarr") == "Severance S02E07"

    def test_sonarr_label_zero_pads_single_digit_episode(self):
        from movieseer.notifier.handlers import labeller

        payload = {
            "series": {"title": "The Bear"},
            "episodes": [{"seasonNumber": 4, "episodeNumber": 1}],
        }
        assert labeller(payload, "sonarr") == "The Bear S04E01"

    def test_sonarr_label_no_episodes(self):
        from movieseer.notifier.handlers import labeller

        payload = {"series": {"title": "Severance"}, "episodes": []}
        assert labeller(payload, "sonarr") == "Severance"
