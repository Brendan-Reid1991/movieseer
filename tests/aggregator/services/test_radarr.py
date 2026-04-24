"""
Tests for RadarrClient (radarr.py).

HTTP calls are avoided by replacing the client's _get method with an AsyncMock.
Tests verify that API responses are correctly parsed into typed Pydantic models.
"""

from unittest.mock import AsyncMock, patch

import pytest

from movieseer.aggregator.services.radarr import (
    Movie,
    RadarrClient,
    RadarrHistory,
    RadarrQueue,
)

_QUALITY = {"quality": {"name": "HD-1080p", "resolution": 1080}}

_MOVIE_RAW = {
    "id": 1,
    "title": "Alien",
    "year": 1979,
    "status": "released",
    "tmdbId": 348,
    "monitored": True,
    "runtime": 117,
    "isAvailable": True,
}

_QUEUE_RAW = {
    "quality": _QUALITY,
    "size": 2_000_000_000.0,
    "title": "Alien",
    "status": "downloading",
    "movieId": 1,
}

_QUEUE_WITH_MOVIE = {
    **_QUEUE_RAW,
    "movie": _MOVIE_RAW,
}

_HISTORY_RAW = {
    "sourceTitle": "Alien.1979.BluRay-SPARKS",
    "quality": _QUALITY,
    "qualityCutoffNotMet": False,
    "date": "2024-01-01T00:00:00Z",
    "eventType": "grabbed",
    "movieId": 1,
}


def _make_client() -> RadarrClient:
    with patch("movieseer.aggregator.services.base.httpx.AsyncClient"):
        return RadarrClient()


class TestRadarrClientQueue:
    """RadarrClient.queue() parses records into RadarrQueue models."""

    async def test_returns_list_of_radarr_queue(self):
        client = _make_client()
        client._get = AsyncMock(return_value={"records": [_QUEUE_RAW]})

        result = await client.queue()

        assert len(result) == 1
        assert isinstance(result[0], RadarrQueue)

    async def test_movie_id_mapped(self):
        client = _make_client()
        client._get = AsyncMock(return_value={"records": [_QUEUE_RAW]})

        result = await client.queue()

        assert result[0].movie_id == 1

    async def test_embedded_movie_parsed(self):
        client = _make_client()
        client._get = AsyncMock(return_value={"records": [_QUEUE_WITH_MOVIE]})

        result = await client.queue()

        assert result[0].movie is not None
        assert isinstance(result[0].movie, Movie)
        assert result[0].movie.title == "Alien"

    async def test_empty_queue_returns_empty_list(self):
        client = _make_client()
        client._get = AsyncMock(return_value={"records": []})

        assert await client.queue() == []

    async def test_include_movie_param_sent(self):
        client = _make_client()
        client._get = AsyncMock(return_value={"records": []})

        await client.queue()

        _, kwargs = client._get.call_args
        assert kwargs["params"]["includeMovie"] is True


class TestRadarrClientMovie:
    """RadarrClient.movie() parses a single movie response into a Movie model."""

    async def test_returns_movie_model(self):
        client = _make_client()
        client._get = AsyncMock(return_value=_MOVIE_RAW)

        result = await client.movie(1)

        assert isinstance(result, Movie)
        assert result.title == "Alien"
        assert result.year == 1979

    async def test_requests_correct_endpoint(self):
        client = _make_client()
        client._get = AsyncMock(return_value=_MOVIE_RAW)

        await client.movie(42)

        client._get.assert_called_once_with("/movie/42")


class TestRadarrClientMovieHistory:
    """RadarrClient.movie_history() parses a list into RadarrHistory models."""

    async def test_returns_list_of_history(self):
        client = _make_client()
        client._get = AsyncMock(return_value=[_HISTORY_RAW])

        result = await client.movie_history(1)

        assert len(result) == 1
        assert isinstance(result[0], RadarrHistory)

    async def test_event_type_and_movie_id_mapped(self):
        client = _make_client()
        client._get = AsyncMock(return_value=[_HISTORY_RAW])

        result = await client.movie_history(1)

        assert result[0].event_type == "grabbed"
        assert result[0].movie_id == 1

    async def test_empty_history_returns_empty_list(self):
        client = _make_client()
        client._get = AsyncMock(return_value=[])

        assert await client.movie_history(1) == []


class TestRadarrClientHistory:
    """RadarrClient.history() fetches the global history log."""

    async def test_returns_list_of_history(self):
        client = _make_client()
        client._get = AsyncMock(return_value={"records": [_HISTORY_RAW]})

        result = await client.history()

        assert len(result) == 1
        assert isinstance(result[0], RadarrHistory)

    async def test_default_sort_is_date_desc(self):
        client = _make_client()
        client._get = AsyncMock(return_value={"records": []})

        await client.history()

        _, kwargs = client._get.call_args
        assert kwargs["params"]["sortKey"] == "date"
        assert kwargs["params"]["sortDir"] == "desc"
