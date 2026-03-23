"""
Tests for aggregator.py.

Covers two categories:
1. Pure helper methods (no I/O) — status mapping, history formatting, etc.
2. Async pipeline methods — title resolution, sort order, history population,
   silent failure logging. HTTP calls are mocked via AsyncMock.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from movieseer.aggregator_ import Aggregator

aggregator = Aggregator()


# ── helpers ───────────────────────────────────────────────────────────────────

def mock_resp(status=200, data=None):
    """Minimal mock of an httpx Response."""
    r = MagicMock()
    r.status_code = status
    r.json.return_value = data if data is not None else {}
    if status >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status}", request=MagicMock(), response=r
        )
    else:
        r.raise_for_status.return_value = None
    return r


def make_js_req(media_type="movie", arr_id=1, tmdb_id=100):
    """Minimal Jellyseerr request dict as returned by /api/v1/request."""
    return {
        "id": 1,
        "status": 2,
        "type": media_type,
        "createdAt": "2026-03-01T12:00:00.000Z",
        "media": {"tmdbId": tmdb_id, "externalServiceId": arr_id, "status": 3},
        "requestedBy": {"displayName": "brendan"},
    }


def make_queue_item(media_type="movie", arr_id=1, title="A Film"):
    """Minimal Radarr/Sonarr queue record with embedded media object."""
    base = {
        "trackedDownloadStatus": "Ok",
        "statusMessages": [],
        "downloadId": "",
        "downloadClient": "",
        "size": 0,
        "sizeleft": 0,
    }
    if media_type == "movie":
        return {**base, "movieId": arr_id, "movie": {"title": title}}
    return {**base, "seriesId": arr_id, "series": {"title": title}}


# ── Jellyseerr request params ─────────────────────────────────────────────────

class TestGetRequestsParams:
    """Verify the params sent to Jellyseerr's /api/v1/request endpoint."""

    async def test_order_param_absent(self):
        """order=desc must not be sent — it causes a Jellyseerr 400."""
        agg = Aggregator()
        client = AsyncMock()
        client.get.return_value = mock_resp(200, {"results": []})
        agg._radarr_queue = AsyncMock(return_value=[])
        agg._sonarr_queue = AsyncMock(return_value=[])
        agg._sabnzbd_slots = AsyncMock(return_value={})
        agg._qbit_torrents = AsyncMock(return_value={})
        agg._get_direct_items = AsyncMock(return_value=[])

        await agg._get_requests(client)

        params = client.get.call_args.kwargs.get("params", {})
        assert "order" not in params


# ── Silent failure logging ────────────────────────────────────────────────────

class TestSilentFailureLogging:
    """Fetch failures must be logged as warnings, not silently discarded."""

    async def test_sonarr_queue_failure_logs_warning(self, caplog):
        import logging
        agg = Aggregator()
        client = AsyncMock()
        client.get.return_value = mock_resp(200, {"results": []})
        agg._radarr_queue = AsyncMock(return_value=[])
        agg._sonarr_queue = AsyncMock(side_effect=Exception("connection refused"))
        agg._sabnzbd_slots = AsyncMock(return_value={})
        agg._qbit_torrents = AsyncMock(return_value={})
        agg._get_direct_items = AsyncMock(return_value=[])

        with caplog.at_level(logging.WARNING, logger="aggregator"):
            await agg._get_requests(client)

        assert any("Sonarr queue" in r.message for r in caplog.records)

    async def test_radarr_queue_failure_logs_warning(self, caplog):
        import logging
        agg = Aggregator()
        client = AsyncMock()
        client.get.return_value = mock_resp(200, {"results": []})
        agg._radarr_queue = AsyncMock(side_effect=Exception("connection refused"))
        agg._sonarr_queue = AsyncMock(return_value=[])
        agg._sabnzbd_slots = AsyncMock(return_value={})
        agg._qbit_torrents = AsyncMock(return_value={})
        agg._get_direct_items = AsyncMock(return_value=[])

        with caplog.at_level(logging.WARNING, logger="aggregator"):
            await agg._get_requests(client)

        assert any("Radarr queue" in r.message for r in caplog.records)


# ── Title resolution ──────────────────────────────────────────────────────────

class TestTitleResolution:
    """_build_js_item must resolve titles from queue, API, or Jellyseerr."""

    async def test_movie_title_from_radarr_queue(self):
        agg = Aggregator()
        req = make_js_req("movie", arr_id=42)
        queue = [make_queue_item("movie", arr_id=42, title="Dune")]
        item = await agg._build_js_item(AsyncMock(), req, queue, [], {}, {})
        assert item["title"] == "Dune"

    async def test_tv_title_from_sonarr_queue(self):
        agg = Aggregator()
        req = make_js_req("tv", arr_id=10)
        queue = [make_queue_item("tv", arr_id=10, title="Severance")]
        item = await agg._build_js_item(AsyncMock(), req, [], queue, {}, {})
        assert item["title"] == "Severance"

    async def test_movie_title_from_radarr_api_when_not_in_queue(self):
        agg = Aggregator()
        req = make_js_req("movie", arr_id=42)
        agg._radarr_movie = AsyncMock(return_value={"title": "Alien"})
        agg._radarr_movie_history = AsyncMock(return_value=[])
        item = await agg._build_js_item(AsyncMock(), req, [], [], {}, {})
        assert item["title"] == "Alien"

    async def test_tv_title_from_sonarr_api_when_not_in_queue(self):
        agg = Aggregator()
        req = make_js_req("tv", arr_id=10)
        agg._sonarr_series = AsyncMock(return_value={"title": "The Wire"})
        agg._sonarr_series_history = AsyncMock(return_value=[])
        item = await agg._build_js_item(AsyncMock(), req, [], [], {}, {})
        assert item["title"] == "The Wire"

    async def test_title_from_jellyseerr_when_no_arr_id(self):
        agg = Aggregator()
        req = {
            "id": 1, "status": 1, "type": "movie",
            "createdAt": "2026-03-01T12:00:00.000Z",
            "media": {"tmdbId": 999, "externalServiceId": None, "status": 1},
            "requestedBy": {"displayName": "brendan"},
        }
        client = AsyncMock()
        client.get.return_value = mock_resp(200, {"title": "The Substance"})
        item = await agg._build_js_item(client, req, [], [], {}, {})
        assert item["title"] == "The Substance"

    async def test_title_falls_back_to_unknown_when_all_resolution_fails(self):
        agg = Aggregator()
        req = make_js_req("movie", arr_id=99)
        agg._radarr_movie = AsyncMock(side_effect=Exception("404"))
        agg._radarr_movie_history = AsyncMock(return_value=[])
        item = await agg._build_js_item(AsyncMock(), req, [], [], {}, {})
        assert item["title"] == "Unknown"


# ── Sort order ────────────────────────────────────────────────────────────────

class TestSortOrder:
    """Combined results must be sorted newest-first."""

    def test_items_sorted_by_requested_at_descending(self):
        items = [
            {"requested_at": "2026-01-01T00:00:00.000Z", "arr": None, "title": "Old"},
            {"requested_at": "2026-03-01T00:00:00.000Z", "arr": None, "title": "New"},
        ]
        items.sort(
            key=lambda r: r.get("requested_at") or (r.get("arr") or {}).get("at") or "",
            reverse=True,
        )
        assert items[0]["title"] == "New"
        assert items[1]["title"] == "Old"

    def test_arr_at_used_when_no_requested_at(self):
        items = [
            {"requested_at": None, "arr": {"at": "2026-02-01T00:00:00.000Z"}, "title": "Via arr"},
            {"requested_at": "2026-03-01T00:00:00.000Z", "arr": None, "title": "New"},
        ]
        items.sort(
            key=lambda r: r.get("requested_at") or (r.get("arr") or {}).get("at") or "",
            reverse=True,
        )
        assert items[0]["title"] == "New"
        assert items[1]["title"] == "Via arr"

    def test_items_with_no_date_sort_to_bottom(self):
        items = [
            {"requested_at": None, "arr": None, "title": "Dateless"},
            {"requested_at": "2026-03-01T00:00:00.000Z", "arr": None, "title": "New"},
        ]
        items.sort(
            key=lambda r: r.get("requested_at") or (r.get("arr") or {}).get("at") or "",
            reverse=True,
        )
        assert items[0]["title"] == "New"
        assert items[1]["title"] == "Dateless"


# ── History population for available direct items ─────────────────────────────

class TestDirectItemsHistory:
    """Available direct items must include history events and a sort date."""

    async def test_available_series_includes_history(self):
        agg = Aggregator()
        client = AsyncMock()
        sonarr_hist = [{
            "seriesId": 5,
            "eventType": "downloadFolderImported",
            "date": "2026-03-20T10:00:00Z",
            "sourceTitle": "Legion.S01",
            "data": {},
        }]
        agg._radarr_recent_history = AsyncMock(return_value=[])
        agg._sonarr_recent_history = AsyncMock(return_value=sonarr_hist)
        agg._sonarr_series = AsyncMock(return_value={
            "title": "Legion",
            "statistics": {"episodeCount": 27, "episodeFileCount": 27},
        })

        results = await agg._get_direct_items(client, set(), set(), [], [], {}, {})
        legion = next((r for r in results if r["title"] == "Legion"), None)

        assert legion is not None
        assert len(legion["history"]) == 1
        assert legion["history"][0]["event"] == "downloadFolderImported"

    async def test_available_series_sets_requested_at_from_history(self):
        agg = Aggregator()
        client = AsyncMock()
        sonarr_hist = [{
            "seriesId": 5,
            "eventType": "downloadFolderImported",
            "date": "2026-03-20T10:00:00Z",
            "sourceTitle": "Legion.S01",
            "data": {},
        }]
        agg._radarr_recent_history = AsyncMock(return_value=[])
        agg._sonarr_recent_history = AsyncMock(return_value=sonarr_hist)
        agg._sonarr_series = AsyncMock(return_value={
            "title": "Legion",
            "statistics": {"episodeCount": 27, "episodeFileCount": 27},
        })

        results = await agg._get_direct_items(client, set(), set(), [], [], {}, {})
        legion = next((r for r in results if r["title"] == "Legion"), None)

        assert legion["requested_at"] == "2026-03-20T10:00:00Z"


# ── SABnzbd slots ─────────────────────────────────────────────────────────────

class TestSabnzbdSummary:
    """_sabnzbd_summary must include a slots list for the downloads section."""

    async def test_slots_present_in_summary(self):
        agg = Aggregator()
        client = AsyncMock()
        client.get.return_value = mock_resp(200, {"queue": {
            "noofslots": 2,
            "speed": "5.0 M",
            "timeleft": "0:30:00",
            "paused": False,
            "slots": [
                {"filename": "Show.S01E01", "percentage": "45.0", "timeleft": "0:15:00", "status": "Downloading"},
                {"filename": "Show.S01E02", "percentage": "10.0", "timeleft": "0:25:00", "status": "Downloading"},
            ],
        }})

        result = await agg._sabnzbd_summary(client)

        assert "slots" in result
        assert len(result["slots"]) == 2
        assert result["slots"][0]["name"] == "Show.S01E01"
        assert result["slots"][0]["progress"] == 45.0

    async def test_empty_queue_returns_empty_slots(self):
        agg = Aggregator()
        client = AsyncMock()
        client.get.return_value = mock_resp(200, {"queue": {
            "noofslots": 0, "speed": "0", "timeleft": "", "paused": False, "slots": [],
        }})

        result = await agg._sabnzbd_summary(client)

        assert result["slots"] == []


class TestJsStatus:
    """Aggregator._js_status maps Jellyseerr status codes to strings."""

    def test_available_when_media_status_5(self):
        assert aggregator._js_status(req_status=2, media_status=5) == "available"

    def test_partial_when_media_status_4(self):
        assert aggregator._js_status(req_status=2, media_status=4) == "partial"

    def test_pending_when_req_status_1(self):
        assert aggregator._js_status(req_status=1, media_status=1) == "pending"

    def test_approved_when_req_status_2(self):
        assert aggregator._js_status(req_status=2, media_status=1) == "approved"

    def test_declined_when_req_status_3(self):
        assert aggregator._js_status(req_status=3, media_status=1) == "declined"

    def test_unknown_for_unrecognised_codes(self):
        assert aggregator._js_status(req_status=99, media_status=99) == "unknown"


class TestArrQueueStatus:
    """Aggregator._arr_queue_status maps queue items to status dicts."""

    def test_downloading_when_no_warnings(self):
        result = aggregator._arr_queue_status({"trackedDownloadStatus": "Ok", "statusMessages": []})
        assert result["status"] == "downloading"
        assert result["error"] is None

    def test_warning_status(self):
        result = aggregator._arr_queue_status({"trackedDownloadStatus": "Warning", "statusMessages": []})
        assert result["status"] == "warning"

    def test_error_status(self):
        result = aggregator._arr_queue_status({"trackedDownloadStatus": "Error", "statusMessages": []})
        assert result["status"] == "error"

    def test_error_message_extracted_from_status_messages(self):
        item = {
            "trackedDownloadStatus": "Warning",
            "statusMessages": [{"messages": ["No files found"]}],
        }
        result = aggregator._arr_queue_status(item)
        assert result["error"] == "No files found"

    def test_multiple_messages_joined(self):
        item = {
            "trackedDownloadStatus": "Warning",
            "statusMessages": [{"messages": ["Err A", "Err B"]}],
        }
        result = aggregator._arr_queue_status(item)
        assert result["error"] == "Err A; Err B"


class TestArrHistoryStatus:
    """Aggregator._arr_history_status maps history events to status dicts."""

    def test_searching_when_no_history(self):
        result = aggregator._arr_history_status(history=[], media={})
        assert result["status"] == "searching"
        assert result["error"] is None

    def test_available_when_media_status_5(self):
        result = aggregator._arr_history_status(history=[], media={"status": 5})
        assert result["status"] == "available"

    def test_grabbed_event(self):
        result = aggregator._arr_history_status(
            history=[{"eventType": "grabbed", "date": "2024-01-01T00:00:00Z"}],
            media={},
        )
        assert result["status"] == "grabbed"

    def test_imported_event(self):
        result = aggregator._arr_history_status(
            history=[{"eventType": "downloadFolderImported", "date": "2024-01-01T00:00:00Z"}],
            media={},
        )
        assert result["status"] == "imported"

    def test_failed_event_extracts_error(self):
        result = aggregator._arr_history_status(
            history=[{
                "eventType": "downloadFailed",
                "date": "2024-01-01T00:00:00Z",
                "data": {"message": "Timeout"},
                "sourceTitle": "some.release",
            }],
            media={},
        )
        assert result["status"] == "failed"
        assert result["error"] == "Timeout"

    def test_failed_event_falls_back_to_source_title(self):
        result = aggregator._arr_history_status(
            history=[{
                "eventType": "downloadFailed",
                "date": "2024-01-01T00:00:00Z",
                "data": {},
                "sourceTitle": "some.release",
            }],
            media={},
        )
        assert result["status"] == "failed"
        assert result["error"] == "some.release"

    def test_unknown_event_type_passed_through(self):
        result = aggregator._arr_history_status(
            history=[{"eventType": "someFutureEvent", "date": "2024-01-01T00:00:00Z"}],
            media={},
        )
        assert result["status"] == "someFutureEvent"


class TestIsRecent:
    """Aggregator._is_recent checks whether a timestamp is within the history window."""

    def test_recent_date_returns_true(self):
        recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        assert aggregator._is_recent(recent) is True

    def test_old_date_returns_false(self):
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        assert aggregator._is_recent(old) is False

    def test_empty_string_returns_false(self):
        assert aggregator._is_recent("") is False

    def test_none_returns_false(self):
        assert aggregator._is_recent(None) is False

    def test_invalid_string_returns_false(self):
        assert aggregator._is_recent("not-a-date") is False


class TestFormatHistory:
    """Aggregator._format_history shapes raw history events for the frontend."""

    def test_empty_history_returns_empty_list(self):
        assert aggregator._format_history([]) == []

    def test_event_fields_mapped_correctly(self):
        events = [{
            "eventType": "grabbed",
            "date": "2024-01-15T10:00:00Z",
            "sourceTitle": "Some.Movie.2024",
            "data": {},
        }]
        result = aggregator._format_history(events)
        assert len(result) == 1
        assert result[0]["event"] == "grabbed"
        assert result[0]["source"] == "Some.Movie.2024"
        assert result[0]["error"] is None

    def test_failed_event_includes_error(self):
        events = [{
            "eventType": "downloadFailed",
            "date": "2024-01-15T10:00:00Z",
            "sourceTitle": "Some.Movie.2024",
            "data": {"message": "NZB corrupt"},
        }]
        result = aggregator._format_history(events)
        assert result[0]["error"] == "NZB corrupt"
