"""SABnzbd API client.

Wraps the SABnzbd JSON API (https://sabnzbd.org/wiki/configuration/4.5/api).
All requests are authenticated via the ``apikey`` query parameter.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar, Literal, TypeVar, cast, overload

from pydantic import BaseModel

from movieseer.config import SABNZBD_API_KEY, SABNZBD_URL

from .client_api import _BaseClient, gateway
from .data_structures.sabnzbd_models import (
    History,
    HistorySlot,
    Queue,
    ServersConfig,
    ServerStat,
    ServerStatsData,
    Slot,
)

T = TypeVar("T", bound=BaseModel)


@gateway("/api")
class SABnzbdClient(_BaseClient):
    """HTTP client for the SABnzbd API.

    Constructs and owns its httpx.AsyncClient. Call ``aclose()`` (or use via
    the Aggregator's lifespan) to release connections on shutdown.

    Auth is handled via ``_DEFAULT_PARAMS``, which is merged into every request.

    Adding a new config section
    ---------------------------
    1. Define a ``BaseModel`` for the section's response in ``sabnzbd_models.py``.
    2. Add an entry to ``_CONFIG_SECTIONS``: ``"section_name": SectionModel``.
    3. Add an ``@overload`` stub for ``get_config`` with the new ``Literal`` and return type.

    Example
    -------
    sabnzbd = SABnzbdClient()
    queue = await sabnzbd.queue()
    health = await sabnzbd.server_health()
    await sabnzbd.aclose()
    """

    SERVICE_URL = SABNZBD_URL

    _DEFAULT_PARAMS: ClassVar[dict[str, str]] = {"apikey": SABNZBD_API_KEY, "output": "json"}

    _CONFIG_SECTIONS: dict[str, type[BaseModel]] = {
        "servers": ServersConfig,
    }

    async def _mode(
        self,
        model: type[T],
        mode: str,
        retrieve: str | None = None,
        params: dict[str, str | int | bool] | None = None,
    ) -> T:
        """Issue a SABnzbd API request and validate the response into ``model``.

        Parameters
        ----------
        model:
            The Pydantic model to validate the response into.
        mode:
            The SABnzbd API ``mode`` parameter (e.g. ``"queue"``, ``"history"``).
        retrieve:
            The top-level key to extract from the JSON response before validation.
            Pass ``None`` to validate the full response dict directly — for endpoints
            whose response is an unwrapped object rather than a keyed envelope.
        params:
            Additional query parameters merged on top of ``_DEFAULT_PARAMS``.
        """
        data = cast(
            "dict[str, object]",
            await self._get(
                "",
                params=self._DEFAULT_PARAMS | {"mode": mode} | (params or {}),
            ),
        )
        if retrieve is None:
            return model.model_validate(data)
        return model.model_validate(data[retrieve])

    async def queue(self) -> Queue:
        """Fetch the current SABnzbd download queue."""
        return await self._mode(model=Queue, mode="queue", retrieve="queue")

    async def history(self) -> History:
        """Fetch the SABnzbd download history (completed and failed jobs)."""
        return await self._mode(model=History, mode="history", retrieve="history")

    async def server_stats(self) -> ServerStatsData:
        """Fetch raw per-server download statistics, keyed by server hostname.

        Article counts are broken down by date (YYYY-MM-DD). Use ``server_health``
        to get aggregated hit-rate statistics instead.
        """
        return await self._mode(model=ServerStatsData, mode="server_stats")

    async def slots(self) -> dict[str, Slot]:
        """Fetch the current queue and return its slots keyed by NZO ID.

        Makes a network request on every call.
        """
        return {slot.nzo_id: slot for slot in (await self.queue()).slots}

    async def slots_history(self) -> dict[str, HistorySlot]:
        """Fetch the download history and return its slots keyed by NZO ID.

        Makes a network request on every call.
        """
        return {slot.nzo_id: slot for slot in (await self.history()).slots}

    @overload
    async def get_config(self, section: Literal["servers"]) -> ServersConfig: ...

    async def get_config(self, section: str) -> BaseModel:
        """Fetch a SABnzbd configuration section.

        The ``section`` must be registered in ``_CONFIG_SECTIONS``, otherwise a
        ``KeyError`` is raised. See the class docstring for how to add new sections.
        """
        return await self._mode(
            self._CONFIG_SECTIONS[section],
            "get_config",
            retrieve="config",
            params={"section": section},
        )

    async def server_health(self) -> list[ServerStat]:
        """Return aggregated per-server hit-rate statistics.

        Fetches ``server_stats`` and ``get_config("servers")`` concurrently,
        then joins them on hostname to annotate each server's article counts
        with its SSL flag. Hit rate is calculated as
        ``articles_success / articles_tried`` across all recorded dates.
        """
        stats, config = await asyncio.gather(
            self.server_stats(),
            self.get_config(section="servers"),
        )
        ssl_map = {server.host: server.ssl for server in config.servers}
        result: list[ServerStat] = []
        for name, server in stats.servers.items():
            tried = sum(server.articles_tried.values())
            success = sum(server.articles_success.values())
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
