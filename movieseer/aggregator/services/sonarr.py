"""Sonarr API v3 client."""

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
from movieseer.config import SONARR_API_KEY, SONARR_URL

type EpisodeHistoryEventType = (
    ArrHistoryEventType
    | Literal[
        "seriesFolderImported",
        "episodeFileDeleted",
        "episodeFileRenamed",
    ]
)
type SeriesStatusType = Literal["continuing", "ended", "upcoming", "deleted"]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SeriesStatistics(_CamelBase):
    """Episode and file counts for a Sonarr series."""

    season_count: int = 0
    episode_count: int = 0
    episode_file_count: int = 0
    total_episode_count: int = 0
    size_on_disk: int = 0
    percent_of_episodes: float = 0.0


class Series(_CamelBase):
    """A Sonarr series record."""

    id: int
    title: str
    year: int
    status: SeriesStatusType
    tvdb_id: int
    imdb_id: str | None = None
    monitored: bool
    runtime: int
    genres: list[str] = Field(default_factory=list)
    statistics: SeriesStatistics | None = None


class SonarrQueue(ArrQueue):
    """Sonarr queue record — extends ArrQueue with episode-specific fields."""

    series_id: int | None = None
    episode_id: int | None = None
    series: Series | None = None  # populated when includeSeries=True


class SonarrHistory(ArrHistory):
    """Sonarr history record — extends ArrHistory with episode-specific fields."""

    series_id: int
    episode_id: int
    event_type: EpisodeHistoryEventType  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class SonarrClient(_ArrClient):
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

    _API_PREFIX = "/api/v3"

    def __init__(self) -> None:
        super().__init__(SONARR_URL, SONARR_API_KEY)

    async def queue(self, page_length: int = 100) -> list[SonarrQueue]:
        """Fetch the current download queue with embedded series details."""
        data = cast(
            "dict[str, list[object]]",
            await self._get(
                "/queue",
                params={"pageSize": page_length, "includeSeries": True},
            ),
        )
        return [SonarrQueue.model_validate(r) for r in data["records"]]

    async def history(
        self,
        page_length: int = 50,
        sort_by: str = "date",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> list[SonarrHistory]:
        """Fetch the global history log, sorted by date descending by default."""
        data = cast(
            "dict[str, list[object]]",
            await self._get(
                "/history",
                params={"pageSize": page_length, "sortKey": sort_by, "sortDir": sort_order},
            ),
        )
        return [SonarrHistory.model_validate(r) for r in data["records"]]

    async def series(self, series_id: int) -> Series:
        """Fetch full details for a single series by its Sonarr ID."""
        data = await self._get(f"/series/{series_id}")
        return Series.model_validate(data)

    async def series_history(self, series_id: int) -> list[SonarrHistory]:
        """Fetch the event history for a specific series."""
        data = cast(
            "list[object]", await self._get("/history/series", params={"seriesId": series_id})
        )
        return [SonarrHistory.model_validate(r) for r in data]
