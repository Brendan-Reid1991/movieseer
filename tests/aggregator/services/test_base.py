"""
Tests for _BaseServiceClient and _ArrClient (base.py).

These tests bypass __init__ to inject a mock httpx.AsyncClient directly,
keeping tests free of real network calls.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from movieseer.aggregator.services.base import _ArrClient, _BaseServiceClient


def _make_base(mock_http: AsyncMock) -> _BaseServiceClient:
    """Return a _BaseServiceClient with the given mock HTTP client injected."""
    client = _BaseServiceClient.__new__(_BaseServiceClient)
    client._client = mock_http
    return client


def _mock_response(data: object, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = data
    if status >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status}", request=MagicMock(), response=r
        )
    else:
        r.raise_for_status.return_value = None
    return r


class TestBaseServiceClientGet:
    """_get issues a GET, calls raise_for_status, and returns parsed JSON."""

    async def test_returns_dict(self):
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=_mock_response({"key": "val"}))
        client = _make_base(mock_http)

        result = await client._get("/path")

        assert result == {"key": "val"}

    async def test_returns_list(self):
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=_mock_response([1, 2, 3]))
        client = _make_base(mock_http)

        result = await client._get("/path")

        assert result == [1, 2, 3]

    async def test_calls_raise_for_status(self):
        mock_resp = _mock_response({})
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        client = _make_base(mock_http)

        await client._get("/path")

        mock_resp.raise_for_status.assert_called_once()

    async def test_passes_params(self):
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=_mock_response({}))
        client = _make_base(mock_http)

        await client._get("/path", params={"key": "val", "n": 5})

        mock_http.get.assert_called_once_with("/path", params={"key": "val", "n": 5})

    async def test_raises_on_http_error(self):
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=_mock_response({}, status=404))
        client = _make_base(mock_http)

        with pytest.raises(httpx.HTTPStatusError):
            await client._get("/path")


class TestBaseServiceClientPost:
    """_post issues a POST and discards the response body."""

    async def test_calls_post_with_data(self):
        mock_http = AsyncMock()
        client = _make_base(mock_http)

        await client._post("/auth", data={"username": "admin", "password": "secret"})

        mock_http.post.assert_called_once_with(
            "/auth", data={"username": "admin", "password": "secret"}
        )

    async def test_returns_none(self):
        mock_http = AsyncMock()
        client = _make_base(mock_http)

        result = await client._post("/auth")

        assert result is None


class TestBaseServiceClientAclose:
    """aclose() delegates to the underlying httpx client."""

    async def test_aclose_called(self):
        mock_http = AsyncMock()
        client = _make_base(mock_http)

        await client.aclose()

        mock_http.aclose.assert_awaited_once()


class TestArrClient:
    """_ArrClient injects X-Api-Key into every request via the httpx client headers."""

    def test_api_key_passed_as_header(self):
        with patch("movieseer.aggregator.services.base.httpx.AsyncClient") as mock_cls:
            _ArrClient("http://radarr:7878", "my-secret-key")

        _, kwargs = mock_cls.call_args
        assert kwargs["headers"]["X-Api-Key"] == "my-secret-key"

    def test_base_url_passed_through(self):
        with patch("movieseer.aggregator.services.base.httpx.AsyncClient") as mock_cls:
            _ArrClient("http://sonarr:8989", "key")

        _, kwargs = mock_cls.call_args
        assert kwargs["base_url"] == "http://sonarr:8989"
