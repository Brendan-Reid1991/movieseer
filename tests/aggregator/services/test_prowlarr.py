"""
Tests for ProwlarrClient (prowlarr.py).

HTTP calls are avoided by replacing _get with an AsyncMock. The status()
method issues two concurrent requests, so side_effect provides ordered returns.
"""

from unittest.mock import AsyncMock, patch

from movieseer.aggregator.services.prowlarr import ProwlarrClient

_ALL_INDEXERS = [{"id": 1}, {"id": 2}, {"id": 3}]
_FAILING_INDEXERS = [{"indexerName": "BadIndexer", "message": "connection timeout"}]


def _make_client() -> ProwlarrClient:
    with patch("movieseer.aggregator.services.base.httpx.AsyncClient"):
        return ProwlarrClient()


class TestProwlarrClientStatus:
    """ProwlarrClient.status() aggregates indexer health from two API calls."""

    async def test_total_count(self):
        client = _make_client()
        # gather calls _get twice: indexerstatus first, indexer second
        client._get = AsyncMock(side_effect=[_FAILING_INDEXERS, _ALL_INDEXERS])

        result = await client.status()

        assert result["total"] == 3

    async def test_failing_count(self):
        client = _make_client()
        client._get = AsyncMock(side_effect=[_FAILING_INDEXERS, _ALL_INDEXERS])

        result = await client.status()

        assert result["failing"] == 1

    async def test_healthy_count(self):
        client = _make_client()
        client._get = AsyncMock(side_effect=[_FAILING_INDEXERS, _ALL_INDEXERS])

        result = await client.status()

        assert result["healthy"] == 2

    async def test_issues_contain_failing_indexer_details(self):
        client = _make_client()
        client._get = AsyncMock(side_effect=[_FAILING_INDEXERS, _ALL_INDEXERS])

        result = await client.status()

        assert len(result["issues"]) == 1
        assert result["issues"][0]["name"] == "BadIndexer"
        assert result["issues"][0]["message"] == "connection timeout"

    async def test_all_healthy_has_no_issues(self):
        client = _make_client()
        client._get = AsyncMock(side_effect=[[], _ALL_INDEXERS])

        result = await client.status()

        assert result["failing"] == 0
        assert result["healthy"] == 3
        assert result["issues"] == []

    async def test_all_failing(self):
        client = _make_client()
        three_failing = [{"indexerName": f"Indexer{i}", "message": "err"} for i in range(3)]
        client._get = AsyncMock(side_effect=[three_failing, _ALL_INDEXERS])

        result = await client.status()

        assert result["failing"] == 3
        assert result["healthy"] == 0
