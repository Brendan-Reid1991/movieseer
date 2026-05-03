"""Radarr API v3 client."""

from __future__ import annotations

from typing import Literal, cast

from pydantic import Field

from movieseer.aggregator.services.base import _ArrClient
from movieseer.aggregator.services.models.arr_models import (
    ArrHistory,
    ArrHistoryEventType,
    ArrQueue,
    _CamelBase,
)
from movieseer.config import RADARR_API_KEY, RADARR_URL

type MovieHistoryEventType = (
    ArrHistoryEventType
    | Literal[
        "movieFolderImported",
        "movieFileDeleted",
        "movieFileRenamed",
    ]
)
type MovieStatusType = Literal["tba", "announced", "inCinemas", "released", "deleted"]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Movie(_CamelBase):
    """A Radarr movie record."""

    id: int
    title: str
    year: int
    status: MovieStatusType
    imdb_id: str | None = None
    tmdb_id: int
    has_file: bool | None = None
    monitored: bool
    size_on_disk: int | None = None
    genres: list[str] = Field(default_factory=list)
    runtime: int
    grabbed: bool | None = None
    is_available: bool
    is_excluded: bool | None = None


class RadarrQueue(ArrQueue):
    """Radarr queue record — extends ArrQueue with movie-specific fields."""

    movie_id: int | None = None
    movie: Movie | None = None  # populated when includeMovie=True


class RadarrHistory(ArrHistory):
    """Radarr history record — extends ArrHistory with movie-specific fields."""

    movie_id: int
    event_type: MovieHistoryEventType  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class RadarrClient(_ArrClient):
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

    BASE_URL = RADARR_URL
    API_KEY = RADARR_API_KEY
    _API_PREFIX = "/api/v3"

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
