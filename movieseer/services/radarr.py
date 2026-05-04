"""Radarr API v3 client."""

from __future__ import annotations

from typing import Literal, cast

from movieseer.config import RADARR_API_KEY, RADARR_URL

from .client_api import _ApiKeyClient, gateway
from .data_structures.radarr_models import (
    Movie,
    RadarrHistory,
    RadarrQueue,
)


@gateway("/api/v3")
class RadarrClient(_ApiKeyClient):
    """Radarr API v3 client.

    Constructs and owns its httpx.AsyncClient. Call ``aclose()`` (or use via
    the Aggregator's lifespan) to release connections on shutdown.

    Example
    -------
    radarr = RadarrClient()
    queue = await radarr.queue()
    film  = await radarr.movie(42)
    await radarr.aclose()
    """

    SERVICE_URL = RADARR_URL
    API_KEY = RADARR_API_KEY

    async def queue(self, page_length: int = 100) -> list[RadarrQueue]:
        """Fetch the current download queue with embedded movie details."""
        data = cast(
            "dict[str, list[object]]",
            await self._get(
                "/queue",
                params={"pageSize": page_length, "includeMovie": True},
            ),
        )
        return [RadarrQueue.model_validate(r) for r in data["records"]]

    async def history(
        self,
        page_length: int = 50,
        sort_by: str = "date",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> list[RadarrHistory]:
        """Fetch the global history log, sorted by date descending by default."""
        data = cast(
            "dict[str, list[object]]",
            await self._get(
                "/history",
                params={"pageSize": page_length, "sortKey": sort_by, "sortDir": sort_order},
            ),
        )
        return [RadarrHistory.model_validate(r) for r in data["records"]]

    async def movie(self, movie_id: int) -> Movie:
        """Fetch full details for a single movie by its Radarr ID."""
        data = await self._get(f"/movie/{movie_id}")
        return Movie.model_validate(data)

    async def movie_history(self, movie_id: int) -> list[RadarrHistory]:
        """Fetch the event history for a specific movie."""
        data = cast(
            "list[object]", await self._get("/history/movie", params={"movieId": movie_id})
        )
        return [RadarrHistory.model_validate(r) for r in data]
