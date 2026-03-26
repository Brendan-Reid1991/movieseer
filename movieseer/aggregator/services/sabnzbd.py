"""SABnzbd API client."""

from __future__ import annotations

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


class SABnzbdClient(_BaseServiceClient):
    """SABnzbd API client.

    Constructs and owns its httpx.AsyncClient. Call ``aclose()`` (or use via
    the Aggregator's lifespan) to release connections on shutdown.

    Auth is via the ``apikey`` query parameter, passed on each request.

    Example
    -------
    sabnzbd = SABnzbdClient()
    queue = await sabnzbd.queue()
    slots = await sabnzbd.slots()
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
