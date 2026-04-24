"""
Tests for QBittorrentClient (qbittorrent.py).

HTTP calls are avoided by mocking _post (used by _login) and _get.
"""

from unittest.mock import AsyncMock, patch

from movieseer.aggregator.services.qbittorrent import QBittorrentClient, Torrent

_TORRENTS = [
    {
        "hash": "ABC123",
        "name": "Movie.2024.BluRay",
        "state": "downloading",
        "progress": 0.5,
        "eta": 3600,
        "size": 2_000_000_000,
    },
    {
        "hash": "DEF456",
        "name": "Show.S01E01.WEB-DL",
        "state": "stalledDL",
        "progress": 0.1,
        "eta": 0,
        "size": 800_000_000,
    },
]


def _make_client() -> QBittorrentClient:
    with patch("movieseer.aggregator.services.base.httpx.AsyncClient"):
        return QBittorrentClient()


class TestQBittorrentClientSummary:
    """QBittorrentClient.summary() counts active and downloading torrents."""

    async def test_active_count(self):
        client = _make_client()
        client._post = AsyncMock()
        client._get = AsyncMock(return_value=_TORRENTS)

        result = await client.summary()

        assert result["active"] == 2

    async def test_downloading_count_excludes_stalled(self):
        client = _make_client()
        client._post = AsyncMock()
        client._get = AsyncMock(return_value=_TORRENTS)

        result = await client.summary()

        # "stalledDL".lower() == "stalleddl" — no "download" substring, excluded
        assert result["downloading"] == 1

    async def test_empty_returns_zeros(self):
        client = _make_client()
        client._post = AsyncMock()
        client._get = AsyncMock(return_value=[])

        result = await client.summary()

        assert result["active"] == 0
        assert result["downloading"] == 0

    async def test_login_called_before_get(self):
        client = _make_client()
        client._post = AsyncMock()
        client._get = AsyncMock(return_value=[])
        call_order = []
        client._post.side_effect = lambda *a, **kw: call_order.append("post") or None
        client._get.side_effect = lambda *a, **kw: call_order.append("get") or []

        await client.summary()

        assert call_order == ["post", "get"]


class TestQBittorrentClientTorrents:
    """QBittorrentClient.torrents() returns all torrents keyed by lowercase hash."""

    async def test_keyed_by_lowercase_hash(self):
        client = _make_client()
        client._post = AsyncMock()
        client._get = AsyncMock(return_value=_TORRENTS)

        result = await client.torrents()

        assert "abc123" in result
        assert "def456" in result

    async def test_values_are_torrent_models(self):
        client = _make_client()
        client._post = AsyncMock()
        client._get = AsyncMock(return_value=_TORRENTS)

        result = await client.torrents()

        assert isinstance(result["abc123"], Torrent)
        assert result["abc123"].name == "Movie.2024.BluRay"
        assert result["abc123"].progress == 0.5

    async def test_empty_returns_empty_dict(self):
        client = _make_client()
        client._post = AsyncMock()
        client._get = AsyncMock(return_value=[])

        assert await client.torrents() == {}
