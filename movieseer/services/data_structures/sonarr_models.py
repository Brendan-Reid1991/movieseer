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

class SonarrQueueEntry(ArrQueueEntry):
    """Sonarr queue record — extends ArrQueueEntry with episode-specific fields."""

    series_id: int | None = None
    episode_id: int | None = None
    series: Series | None = None  # populated when includeSeries=True


class SonarrHistoryEntry(ArrHistoryEntry[EpisodeHistoryEventType]):
    """Sonarr history record — extends ArrHistoryEntry with episode-specific fields."""

    series_id: int
    episode_id: int
