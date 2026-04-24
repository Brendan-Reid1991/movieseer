"""SABnzbd API client."""

from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel, Field

from movieseer.aggregator.services.base import _BaseServiceClient
from movieseer.config import SABNZBD_API_KEY, SABNZBD_URL


class Slot(BaseModel):
    """A single slot entry from the SABnzbd queue API.

    A subset of the slots entry in https://sabnzbd.org/wiki/configuration/4.5/api#queue
    """

    nzo_id: str
    name: str = Field(alias="filename")
    progress: float = Field(alias="percentage")
    eta: str = Field(alias="timeleft")
    status: str


class Queue(BaseModel):
    """Top-level queue object from the SABnzbd queue API.

    A subset of the queue object from
    https://sabnzbd.org/wiki/configuration/4.5/api#queue
    """

    count: int = Field(alias="noofslots")
    speed: str
    eta: str = Field(alias="timeleft")
    paused: bool
    slots: list[Slot]


class ServerStat(TypedDict):
    """Hit-rate statistics for a single SABnzbd news server (cumulative totals)."""

    name: str
    ssl: bool
    articles_tried: int    # total download attempts (all-time sum of per-day counts)
    articles_success: int  # successful downloads (all-time sum of per-day counts)
    hit_rate: float        # articles_success / articles_tried, or 0.0 if zero


class SABnzbdClient(_BaseServiceClient):
    """SABnzbd API client.

    Constructs and owns its httpx.AsyncClient. Call ``aclose()`` (or use via
    the Aggregator's lifespan) to release connections on shutdown.

    Auth is via the ``apikey`` query parameter, passed on each request.

    Example
    -------
    sabnzbd = SABnzbdClient()
    queue = await sabnzbd.queue()
    stats = await sabnzbd.server_stats()
    await sabnzbd.aclose()
    """

    _API_PREFIX = "/api"

    def __init__(self) -> None:
        super().__init__(SABNZBD_URL)

    async def queue(self) -> Queue:
        """Fetch the SABnzbd queue.

        Raises
        ------
        httpx.HTTPStatusError
            If the SABnzbd API returns a non-2xx response.
        """
        data = await self._get(
            "",
            params={"mode": "queue", "apikey": SABNZBD_API_KEY, "output": "json"},
        )
        return Queue.model_validate(data["queue"])

    async def slots(self) -> dict[str, Slot]:
        """Return the current queue slots keyed by NZO ID."""
        return {slot.nzo_id: slot for slot in (await self.queue()).slots}

    async def server_stats(self) -> list[ServerStat]:
        """Return per-server hit-rate statistics for the last 24 hours.

        Fetches ``mode=server_stats`` and ``mode=get_config&section=servers``
        concurrently so we can annotate each server with its SSL flag (which
        is not present in the stats response).

        Raises
        ------
        httpx.HTTPStatusError
            If either SABnzbd API call returns a non-2xx response.
        """
        import asyncio

        stats_data, config_data = await asyncio.gather(
            self._get("", params={"mode": "server_stats", "apikey": SABNZBD_API_KEY, "output": "json"}),
            self._get("", params={"mode": "get_config", "section": "servers", "apikey": SABNZBD_API_KEY, "output": "json"}),
        )

        # Build SSL map: server host → ssl bool
        ssl_map: dict[str, bool] = {}
        for srv in (config_data or {}).get("config", {}).get("servers", []):  # type: ignore[union-attr]
            ssl_map[srv.get("host", "")] = bool(srv.get("ssl", False))

        servers: dict[str, object] = (stats_data or {}).get("servers", {})  # type: ignore[union-attr]
        result: list[ServerStat] = []

        for name, srv_stats in servers.items():  # type: ignore[union-attr]
            # articles_tried / articles_success are dicts keyed by date label (YYYYMMDD)
            tried_by_day: dict[str, int] = srv_stats.get("articles_tried", {})  # type: ignore[union-attr]
            success_by_day: dict[str, int] = srv_stats.get("articles_success", {})  # type: ignore[union-attr]
            tried: int = sum(tried_by_day.values()) if tried_by_day else 0
            success: int = sum(success_by_day.values()) if success_by_day else 0
            hit_rate = round(success / tried, 4) if tried > 0 else 0.0
            result.append(
                ServerStat(
                    name=name,
                    ssl=ssl_map.get(name, False),
                    articles_tried=tried,
                    articles_success=success,
                    hit_rate=hit_rate,
                )
            )

        return result
