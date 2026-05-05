from typing import Literal

from pydantic import Field

from .arr_models import (
    ArrHistoryEntry,
    ArrHistoryEventType,
    ArrQueueEntry,
    _CamelBase,
)

type EpisodeHistoryEventType = (
    ArrHistoryEventType
    | Literal[
        "seriesFolderImported",
        "episodeFileDeleted",
        "episodeFileRenamed",
    ]
)

type SeriesStatusType = Literal["continuing", "ended", "upcoming", "deleted"]

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


class SonarrQueueEntry(ArrQueueEntry):
    """Sonarr queue record — extends ArrQueueEntry with episode-specific fields."""

    series_id: int | None = None
    episode_id: int | None = None
    series: Series | None = None  # populated when includeSeries=True


class SonarrHistoryEntry(ArrHistoryEntry[EpisodeHistoryEventType]):
    """Sonarr history record — extends ArrHistoryEntry with episode-specific fields."""

    series_id: int
    episode_id: int

