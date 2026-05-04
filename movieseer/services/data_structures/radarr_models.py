from typing import Literal

from pydantic import Field

from .arr_models import ArrHistory, ArrHistoryEventType, ArrQueue, _CamelBase

type MovieHistoryEventType = (
    ArrHistoryEventType
    | Literal[
        "movieFileDeleted",
        "movieFileRenamed",
    ]
)
type MovieStatusType = Literal["tba", "announced", "inCinemas", "released", "deleted"]


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
