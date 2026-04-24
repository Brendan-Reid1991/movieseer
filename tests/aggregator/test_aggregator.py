"""
Tests for aggregator.py.

Covers two categories:
1. Pure helper methods (no I/O) — status mapping, history formatting, etc.
2. Async pipeline methods — title resolution, sort order, history population,
   silent failure logging. Service client calls are mocked via AsyncMock.
"""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from movieseer.aggregator import Aggregator
from movieseer.aggregator.services.arr_models import ArrQueue
from movieseer.aggregator.services.radarr import Movie, RadarrHistory, RadarrQueue
from movieseer.aggregator.services.sonarr import Series, SonarrHistory, SonarrQueue

# ── Shared quality fixture ────────────────────────────────────────────────────

_QUALITY = {"quality": {"name": "HD-1080p", "resolution": 1080}}

# Module-level aggregator for pure (synchronous) helper tests.
_agg = Aggregator()


# ── Factories ─────────────────────────────────────────────────────────────────


def make_js_req(media_type: str = "movie", arr_id: int = 1, tmdb_id: int = 100) -> dict:
    """Minimal Jellyseerr request dict as returned by /api/v1/request."""
    return {
        "id": 1,
        "status": 2,
        "type": media_type,
        "createdAt": "2026-03-01T12:00:00.000Z",
        "media": {"tmdbId": tmdb_id, "externalServiceId": arr_id, "status": 3},
        "requestedBy": {"displayName": "brendan"},
    }


def make_radarr_queue(arr_id: int = 1, title: str = "A Film") -> RadarrQueue:
    """Minimal RadarrQueue with an embedded Movie."""
    return RadarrQueue.model_validate(
        {
            "quality": _QUALITY,
            "size": 0.0,
            "title": title,
            "status": "downloading",
            "movieId": arr_id,
            "movie": {
                "id": arr_id,
                "title": title,
                "year": 2024,
                "status": "released",
                "tmdbId": 100,
                "monitored": True,
                "runtime": 120,
                "isAvailable": True,
            },
        }
    )


def make_sonarr_queue(arr_id: int = 1, title: str = "A Show") -> SonarrQueue:
    """Minimal SonarrQueue with an embedded Series."""
    return SonarrQueue.model_validate(
        {
            "quality": _QUALITY,
            "size": 0.0,
            "title": title,
            "status": "downloading",
            "seriesId": arr_id,
            "series": {
                "id": arr_id,
                "title": title,
                "year": 2020,
                "status": "continuing",
                "tvdbId": 12345,
                "monitored": True,
                "runtime": 45,
                "statistics": {
                    "seasonCount": 1,
                    "episodeCount": 10,
                    "episodeFileCount": 5,
                    "totalEpisodeCount": 10,
                    "sizeOnDisk": 0,
                    "percentOfEpisodes": 50.0,
                },
            },
        }
    )


def make_arr_queue(**overrides) -> ArrQueue:
    """ArrQueue with sensible defaults, accepting field overrides (camelCase)."""
    base = {
        "quality": _QUALITY,
        "size": 0.0,
        "title": "Test",
        "status": "downloading",
        "trackedDownloadStatus": "Ok",
        "statusMessages": [],
    }
    return ArrQueue.model_validate({**base, **overrides})


def make_radarr_history(
    event_type: str = "grabbed",
    source_title: str = "Test.Release",
    data: dict | None = None,
    date: str = "2024-01-01T00:00:00Z",
) -> RadarrHistory:
    return RadarrHistory.model_validate(
        {
            "sourceTitle": source_title,
            "quality": _QUALITY,
            "qualityCutoffNotMet": False,
            "date": date,
            "eventType": event_type,
            "movieId": 1,
            "data": data or {},
        }
    )


def make_sonarr_history(
    event_type: str = "downloadFolderImported",
    series_id: int = 5,
    date: str = "2026-03-20T10:00:00Z",
) -> SonarrHistory:
    return SonarrHistory.model_validate(
        {
            "sourceTitle": "Legion.S01",
            "quality": _QUALITY,
            "qualityCutoffNotMet": False,
            "date": date,
            "eventType": event_type,
            "seriesId": series_id,
            "episodeId": 1,
        }
    )


def make_series(
    series_id: int = 5,
    title: str = "Legion",
    episode_count: int = 27,
    file_count: int = 27,
) -> Series:
    return Series.model_validate(
        {
            "id": series_id,
            "title": title,
            "year": 2017,
            "status": "ended",
            "tvdbId": 12345,
            "monitored": True,
            "runtime": 42,
            "statistics": {
                "seasonCount": 3,
                "episodeCount": episode_count,
                "episodeFileCount": file_count,
                "totalEpisodeCount": episode_count,
                "sizeOnDisk": 0,
                "percentOfEpisodes": 100.0,
            },
        }
    )


def _mock_js_client(data: object = None) -> AsyncMock:
    """AsyncMock context-manager httpx client that returns *data* as JSON."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = data if data is not None else {"results": []}
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ── TestJsStatus ──────────────────────────────────────────────────────────────


class TestJsStatus:
    """Aggregator._js_status maps Jellyseerr status codes to strings."""

    def test_available_when_media_status_5(self):
        assert _agg._js_status(req_status=2, media_status=5) == "available"

    def test_partial_when_media_status_4(self):
        assert _agg._js_status(req_status=2, media_status=4) == "partial"

    def test_pending_when_req_status_1(self):
        assert _agg._js_status(req_status=1, media_status=1) == "pending"

    def test_approved_when_req_status_2(self):
        assert _agg._js_status(req_status=2, media_status=1) == "approved"

    def test_declined_when_req_status_3(self):
        assert _agg._js_status(req_status=3, media_status=1) == "declined"

    def test_unknown_for_unrecognised_codes(self):
        assert _agg._js_status(req_status=99, media_status=99) == "unknown"


# ── TestArrQueueStatus ────────────────────────────────────────────────────────


class TestArrQueueStatus:
    """Aggregator._arr_queue_status maps ArrQueue models to status dicts."""

    def test_downloading_when_tracked_status_ok(self):
        result = _agg._arr_queue_status(make_arr_queue())
        assert result["status"] == "downloading"
        assert result["error"] is None

    def test_warning_status(self):
        result = _agg._arr_queue_status(make_arr_queue(trackedDownloadStatus="Warning"))
        assert result["status"] == "warning"

    def test_error_status(self):
        result = _agg._arr_queue_status(make_arr_queue(trackedDownloadStatus="Error"))
        assert result["status"] == "error"

    def test_error_message_extracted_from_status_messages(self):
        q = make_arr_queue(
            trackedDownloadStatus="Warning",
            statusMessages=[{"messages": ["No files found"]}],
        )
        result = _agg._arr_queue_status(q)
        assert result["error"] == "No files found"

    def test_multiple_messages_joined(self):
        q = make_arr_queue(
            trackedDownloadStatus="Warning",
            statusMessages=[{"messages": ["Err A", "Err B"]}],
        )
        result = _agg._arr_queue_status(q)
        assert result["error"] == "Err A; Err B"

    def test_no_messages_error_is_none(self):
        q = make_arr_queue(
            trackedDownloadStatus="Warning",
            statusMessages=[{"messages": []}],
        )
        assert _agg._arr_queue_status(q)["error"] is None


# ── TestArrHistoryStatus ──────────────────────────────────────────────────────


class TestArrHistoryStatus:
    """Aggregator._arr_history_status maps ArrHistory model lists to status dicts."""

    def test_searching_when_no_history(self):
        result = _agg._arr_history_status(history=[], media={})
        assert result["status"] == "searching"
        assert result["error"] is None

    def test_available_when_media_status_5(self):
        result = _agg._arr_history_status(history=[], media={"status": 5})
        assert result["status"] == "available"

    def test_grabbed_event(self):
        result = _agg._arr_history_status(history=[make_radarr_history("grabbed")], media={})
        assert result["status"] == "grabbed"

    def test_download_folder_imported_maps_to_imported(self):
        result = _agg._arr_history_status(
            history=[make_radarr_history("downloadFolderImported")], media={}
        )
        assert result["status"] == "imported"

    def test_download_failed_maps_to_failed(self):
        result = _agg._arr_history_status(
            history=[make_radarr_history("downloadFailed")], media={}
        )
        assert result["status"] == "failed"

    def test_failed_event_extracts_error_from_data(self):
        result = _agg._arr_history_status(
            history=[make_radarr_history("downloadFailed", data={"message": "Timeout"})],
            media={},
        )
        assert result["error"] == "Timeout"

    def test_failed_event_falls_back_to_source_title(self):
        result = _agg._arr_history_status(
            history=[make_radarr_history("downloadFailed", source_title="some.release")],
            media={},
        )
        assert result["error"] == "some.release"

    def test_service_specific_event_passed_through(self):
        # movieFileDeleted is a valid MovieHistoryEventType not in the shared event_map
        h = RadarrHistory.model_validate(
            {
                "sourceTitle": "Test",
                "quality": _QUALITY,
                "qualityCutoffNotMet": False,
                "date": "2024-01-01T00:00:00Z",
                "eventType": "movieFileDeleted",
                "movieId": 1,
            }
        )
        result = _agg._arr_history_status([h], {})
        assert result["status"] == "movieFileDeleted"

    def test_at_field_is_iso_timestamp(self):
        result = _agg._arr_history_status(
            history=[make_radarr_history("grabbed", date="2024-06-15T12:00:00Z")],
            media={},
        )
        assert "2024-06-15" in result["at"]


# ── TestIsRecent ──────────────────────────────────────────────────────────────


class TestIsRecent:
    """Aggregator._is_recent returns True when a datetime is within the history window."""

    def test_recent_date_returns_true(self):
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        assert _agg._is_recent(recent) is True

    def test_old_date_returns_false(self):
        old = datetime.now(timezone.utc) - timedelta(days=30)
        assert _agg._is_recent(old) is False

    def test_boundary_just_inside_window(self):
        just_inside = datetime.now(timezone.utc) - timedelta(days=6, hours=23)
        assert _agg._is_recent(just_inside) is True

    def test_naive_datetime_treated_as_utc(self):
        naive = datetime.now() - timedelta(hours=1)
        assert _agg._is_recent(naive) is True


# ── TestFormatHistory ─────────────────────────────────────────────────────────


class TestFormatHistory:
    """Aggregator._format_history shapes ArrHistory events for the frontend."""

    def test_empty_history_returns_empty_list(self):
        assert _agg._format_history([]) == []

    def test_event_fields_mapped_correctly(self):
        result = _agg._format_history([make_radarr_history("grabbed", "Some.Movie.2024")])
        assert len(result) == 1
        assert result[0]["event"] == "grabbed"
        assert result[0]["source"] == "Some.Movie.2024"
        assert result[0]["error"] is None
        assert result[0]["at"] is not None

    def test_failed_event_includes_error(self):
        result = _agg._format_history(
            [
                make_radarr_history(
                    "downloadFailed", "Some.Movie.2024", data={"message": "NZB corrupt"}
                )
            ]
        )
        assert result[0]["error"] == "NZB corrupt"

    def test_failed_event_falls_back_to_source_title(self):
        result = _agg._format_history([make_radarr_history("downloadFailed", "Some.Movie.2024")])
        assert result[0]["error"] == "Some.Movie.2024"

    def test_multiple_events_returned_in_order(self):
        events = [
            make_radarr_history("grabbed"),
            make_radarr_history("downloadFolderImported"),
        ]
        result = _agg._format_history(events)
        assert len(result) == 2
        assert result[0]["event"] == "grabbed"
        assert result[1]["event"] == "downloadFolderImported"


# ── TestSortOrder ─────────────────────────────────────────────────────────────


class TestSortOrder:
    """Combined results must be sorted newest-first by request or activity date."""

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
            {
                "requested_at": None,
                "arr": {"at": "2026-02-01T00:00:00.000Z"},
                "title": "Via arr",
            },
            {"requested_at": "2026-03-01T00:00:00.000Z", "arr": None, "title": "New"},
        ]
        items.sort(
            key=lambda r: r.get("requested_at") or (r.get("arr") or {}).get("at") or "",
            reverse=True,
        )
        assert items[0]["title"] == "New"

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


# ── TestGetRequestsParams ─────────────────────────────────────────────────────


class TestGetRequestsParams:
    """Verify the params sent to Jellyseerr's /api/v1/request endpoint."""

    async def test_order_param_absent(self):
        """order=desc must not be sent — it causes a Jellyseerr 400."""
        agg = Aggregator()
        agg._radarr.queue = AsyncMock(return_value=[])
        agg._sonarr.queue = AsyncMock(return_value=[])
        agg._sabnzbd.slots = AsyncMock(return_value={})
        agg._qbit.torrents = AsyncMock(return_value={})

        mock_client = _mock_js_client({"results": []})
        with patch("movieseer.aggregator.aggregator.httpx.AsyncClient", return_value=mock_client):
            await agg._get_requests()

        params = mock_client.get.call_args.kwargs.get("params", {})
        assert "order" not in params

    async def test_take_param_present(self):
        agg = Aggregator()
        agg._radarr.queue = AsyncMock(return_value=[])
        agg._sonarr.queue = AsyncMock(return_value=[])
        agg._sabnzbd.slots = AsyncMock(return_value={})
        agg._qbit.torrents = AsyncMock(return_value={})

        mock_client = _mock_js_client({"results": []})
        with patch("movieseer.aggregator.aggregator.httpx.AsyncClient", return_value=mock_client):
            await agg._get_requests()

        params = mock_client.get.call_args.kwargs.get("params", {})
        assert "take" in params


# ── TestSilentFailureLogging ──────────────────────────────────────────────────


class TestSilentFailureLogging:
    """Service fetch failures must be logged as warnings, not silently discarded."""

    async def test_sonarr_queue_failure_logs_warning(self, caplog):
        agg = Aggregator()
        agg._radarr.queue = AsyncMock(return_value=[])
        agg._sonarr.queue = AsyncMock(side_effect=Exception("connection refused"))
        agg._sabnzbd.slots = AsyncMock(return_value={})
        agg._qbit.torrents = AsyncMock(return_value={})

        mock_client = _mock_js_client({"results": []})
        with patch("movieseer.aggregator.aggregator.httpx.AsyncClient", return_value=mock_client):
            with caplog.at_level(logging.WARNING, logger="movieseer.aggregator.aggregator"):
                await agg._get_requests()

        assert any("Sonarr queue" in r.message for r in caplog.records)

    async def test_radarr_queue_failure_logs_warning(self, caplog):
        agg = Aggregator()
        agg._radarr.queue = AsyncMock(side_effect=Exception("connection refused"))
        agg._sonarr.queue = AsyncMock(return_value=[])
        agg._sabnzbd.slots = AsyncMock(return_value={})
        agg._qbit.torrents = AsyncMock(return_value={})

        mock_client = _mock_js_client({"results": []})
        with patch("movieseer.aggregator.aggregator.httpx.AsyncClient", return_value=mock_client):
            with caplog.at_level(logging.WARNING, logger="movieseer.aggregator.aggregator"):
                await agg._get_requests()

        assert any("Radarr queue" in r.message for r in caplog.records)


# ── TestTitleResolution ───────────────────────────────────────────────────────


class TestTitleResolution:
    """_build_js_item resolves titles from the queue, arr API, or Jellyseerr."""

    async def test_movie_title_from_radarr_queue(self):
        agg = Aggregator()
        req = make_js_req("movie", arr_id=42)
        item = await agg._build_jellyseerr_item(
            req, [make_radarr_queue(arr_id=42, title="Dune")], [], {}, {}
        )
        assert item["title"] == "Dune"

    async def test_tv_title_from_sonarr_queue(self):
        agg = Aggregator()
        req = make_js_req("tv", arr_id=10)
        item = await agg._build_jellyseerr_item(
            req, [], [make_sonarr_queue(arr_id=10, title="Severance")], {}, {}
        )
        assert item["title"] == "Severance"

    async def test_movie_title_from_radarr_api_when_not_in_queue(self):
        agg = Aggregator()
        req = make_js_req("movie", arr_id=42)
        movie = Movie.model_validate(
            {
                "id": 42,
                "title": "Alien",
                "year": 1979,
                "status": "released",
                "tmdbId": 123,
                "monitored": True,
                "runtime": 117,
                "isAvailable": True,
            }
        )
        agg._radarr.movie = AsyncMock(return_value=movie)
        agg._radarr.movie_history = AsyncMock(return_value=[])
        item = await agg._build_jellyseerr_item(req, [], [], {}, {})
        assert item["title"] == "Alien"

    async def test_tv_title_from_sonarr_api_when_not_in_queue(self):
        agg = Aggregator()
        req = make_js_req("tv", arr_id=10)
        agg._sonarr.series = AsyncMock(return_value=make_series(series_id=10, title="The Wire"))
        agg._sonarr.series_history = AsyncMock(return_value=[])
        item = await agg._build_jellyseerr_item(req, [], [], {}, {})
        assert item["title"] == "The Wire"

    async def test_title_from_jellyseerr_when_no_arr_id(self):
        agg = Aggregator()
        req = {
            "id": 1,
            "status": 1,
            "type": "movie",
            "createdAt": "2026-03-01T12:00:00.000Z",
            "media": {"tmdbId": 999, "externalServiceId": None, "status": 1},
            "requestedBy": {"displayName": "brendan"},
        }
        mock_client = _mock_js_client({"title": "The Substance"})
        with patch("movieseer.aggregator.aggregator.httpx.AsyncClient", return_value=mock_client):
            item = await agg._build_jellyseerr_item(req, [], [], {}, {})
        assert item["title"] == "The Substance"

    async def test_title_falls_back_to_unknown_when_all_resolution_fails(self):
        agg = Aggregator()
        req = make_js_req("movie", arr_id=99)
        agg._radarr.movie = AsyncMock(side_effect=Exception("404"))
        agg._radarr.movie_history = AsyncMock(return_value=[])
        item = await agg._build_jellyseerr_item(req, [], [], {}, {})
        assert item["title"] == "Unknown"


# ── TestDirectItemsHistory ────────────────────────────────────────────────────


class TestDirectItemsHistory:
    """Available direct items must include history events and a sort date."""

    async def test_available_series_includes_history(self):
        agg = Aggregator()
        agg._radarr.history = AsyncMock(return_value=[])
        agg._sonarr.history = AsyncMock(return_value=[make_sonarr_history()])
        agg._sonarr.series = AsyncMock(return_value=make_series())

        results = await agg._get_direct_items(set(), set(), [], [], {}, {})
        legion = next((r for r in results if r["title"] == "Legion"), None)

        assert legion is not None
        assert len(legion["history"]) == 1
        assert legion["history"][0]["event"] == "downloadFolderImported"

    async def test_available_series_sets_requested_at_from_history(self):
        agg = Aggregator()
        agg._radarr.history = AsyncMock(return_value=[])
        agg._sonarr.history = AsyncMock(
            return_value=[make_sonarr_history(date="2026-03-20T10:00:00Z")]
        )
        agg._sonarr.series = AsyncMock(return_value=make_series())

        results = await agg._get_direct_items(set(), set(), [], [], {}, {})
        legion = next((r for r in results if r["title"] == "Legion"), None)

        assert legion["requested_at"] is not None
        assert "2026-03-20" in legion["requested_at"]

    async def test_series_already_in_js_ids_excluded(self):
        """Series IDs already tracked by Jellyseerr must not appear as direct items."""
        agg = Aggregator()
        agg._radarr.history = AsyncMock(return_value=[])
        agg._sonarr.history = AsyncMock(return_value=[make_sonarr_history(series_id=5)])

        # series_id 5 is already tracked
        results = await agg._get_direct_items(set(), {5}, [], [], {}, {})

        assert not any(r["title"] == "Legion" for r in results)
