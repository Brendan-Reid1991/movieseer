"""Sonarr API v3 client."""

from __future__ import annotations

from typing import Literal, cast

from movieseer.config import SONARR_API_KEY, SONARR_URL

from .client_api import _ApiKeyClient, gateway
from .data_structures.sonarr_models import Series, SonarrHistoryEntry, SonarrQueueEntry


@gateway("/api/v3")
class SonarrClient(_ApiKeyClient):
    """Sonarr API v3 client.

    Constructs and owns its httpx.AsyncClient. Call ``aclose()`` (or use via
    the Aggregator's lifespan) to release connections on shutdown.

    Example
    -------
    sonarr = SonarrClient()
    queue = await sonarr.queue()
    show  = await sonarr.series(42)
    await sonarr.aclose()
    """

    SERVICE_URL = SONARR_URL
    API_KEY = SONARR_API_KEY

    async def queue(self, page_length: int = 100) -> list[SonarrQueueEntry]:
        """Fetch the current download queue with embedded series details."""
        data = cast(
            "dict[str, list[object]]",
            await self._get(
                "/queue",
                params={"pageSize": page_length, "includeSeries": True},
            ),
        )
        return [SonarrQueueEntry.model_validate(r) for r in data["records"]]

    async def history(
        self,
        page_length: int = 50,
        sort_by: str = "date",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> list[SonarrHistoryEntry]:
        """Fetch the global history log, sorted by date descending by default."""
        data = cast(
            "dict[str, list[object]]",
            await self._get(
                "/history",
                params={"pageSize": page_length, "sortKey": sort_by, "sortDir": sort_order},
            ),
        )
        return [SonarrHistoryEntry.model_validate(r) for r in data["records"]]

    async def series(self, series_id: int) -> Series:
        """Fetch full details for a single series by its Sonarr ID."""
        data = await self._get(f"/series/{series_id}")
        return Series.model_validate(data)

    async def series_history(self, series_id: int) -> list[SonarrHistoryEntry]:
        """Fetch the event history for a specific series."""
        data = cast(
            "list[object]", await self._get("/history/series", params={"seriesId": series_id})
        )
        return [SonarrHistoryEntry.model_validate(r) for r in data]
