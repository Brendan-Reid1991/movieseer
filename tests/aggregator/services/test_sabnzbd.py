"""
Tests for SABnzbdClient (sabnzbd.py).

HTTP calls are avoided by replacing the client's _get method with an AsyncMock.
"""

from unittest.mock import AsyncMock, patch

from movieseer.aggregator.services.sabnzbd import Queue, SABnzbdClient, Slot

_FULL_QUEUE_RESPONSE = {
    "queue": {
        "noofslots": 2,
        "speed": "5.0 M",
        "timeleft": "0:30:00",
        "paused": False,
        "slots": [
            {
                "nzo_id": "nzo1",
                "filename": "Show.S01E01",
                "percentage": "45.0",
                "timeleft": "0:15:00",
                "status": "Downloading",
            },
            {
                "nzo_id": "nzo2",
                "filename": "Show.S01E02",
                "percentage": "10.0",
                "timeleft": "0:25:00",
                "status": "Downloading",
            },
        ],
    }
}

_EMPTY_QUEUE_RESPONSE = {
    "queue": {
        "noofslots": 0,
        "speed": "0",
        "timeleft": "",
        "paused": False,
        "slots": [],
    }
}


def _make_client() -> SABnzbdClient:
    with patch("movieseer.aggregator.services.base.httpx.AsyncClient"):
        return SABnzbdClient()


class TestSABnzbdClientQueue:
    """SABnzbdClient.queue() parses the SABnzbd queue API response."""

    async def test_returns_queue_model(self):
        client = _make_client()
        client._get = AsyncMock(return_value=_FULL_QUEUE_RESPONSE)

        result = await client.queue()

        assert isinstance(result, Queue)

    async def test_slot_count(self):
        client = _make_client()
        client._get = AsyncMock(return_value=_FULL_QUEUE_RESPONSE)

        result = await client.queue()

        assert result.count == 2

    async def test_paused_flag(self):
        client = _make_client()
        client._get = AsyncMock(return_value=_FULL_QUEUE_RESPONSE)

        result = await client.queue()

        assert result.paused is False

    async def test_slot_name_and_progress(self):
        client = _make_client()
        client._get = AsyncMock(return_value=_FULL_QUEUE_RESPONSE)

        result = await client.queue()

        assert result.slots[0].name == "Show.S01E01"
        assert result.slots[0].progress == 45.0

    async def test_empty_queue(self):
        client = _make_client()
        client._get = AsyncMock(return_value=_EMPTY_QUEUE_RESPONSE)

        result = await client.queue()

        assert result.count == 0
        assert result.slots == []


class TestSABnzbdClientSlots:
    """SABnzbdClient.slots() returns a dict of Slot models keyed by nzo_id."""

    async def test_keyed_by_nzo_id(self):
        client = _make_client()
        client._get = AsyncMock(return_value=_FULL_QUEUE_RESPONSE)

        result = await client.slots()

        assert "nzo1" in result
        assert "nzo2" in result

    async def test_values_are_slot_models(self):
        client = _make_client()
        client._get = AsyncMock(return_value=_FULL_QUEUE_RESPONSE)

        result = await client.slots()

        assert isinstance(result["nzo1"], Slot)

    async def test_empty_queue_returns_empty_dict(self):
        client = _make_client()
        client._get = AsyncMock(return_value=_EMPTY_QUEUE_RESPONSE)

        assert await client.slots() == {}
