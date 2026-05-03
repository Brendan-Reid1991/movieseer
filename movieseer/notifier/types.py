from enum import StrEnum
from typing import Literal, TypedDict


class ArrWebhookEvent(StrEnum):
    """Webhooks emitted from Radarr and Sonarr."""

    Grab = "Grab"
    Download = "Download"
    DownloadFailure = "DownloadFailure"
    ImportFailure = "ImportFailure"
    ManualInteractionRequired = "ManualInteractionRequired"
    Health = "Health"


Services = Literal["radarr", "sonarr"]
Priority = Literal["low", "default", "high", "urgent"]


# --- Shared ---


class ReleaseInfo(TypedDict, total=False):
    """Release metadata included in grab events."""

    indexer: str
    quality: str


# --- Webhook handler payloads ---


class GrabPayload(TypedDict, total=False):
    """Payload fields consumed by the grab handler."""

    release: ReleaseInfo


class MessagePayload(TypedDict, total=False):
    """Payload fields consumed by failure and interaction handlers."""

    message: str


class HealthPayload(TypedDict, total=False):
    """Payload fields consumed by the health handler."""

    message: str
    level: str


# --- Service-specific payloads ---


class MovieInfo(TypedDict, total=False):
    """Movie metadata from a Radarr payload."""

    title: str
    year: int


class SeriesInfo(TypedDict, total=False):
    """Series metadata from a Sonarr payload."""

    title: str


class EpisodeInfo(TypedDict, total=False):
    """Episode metadata from a Sonarr payload."""

    seasonNumber: int
    episodeNumber: int


class ArrPayload(TypedDict, total=False):
    """Fields shared by all Radarr and Sonarr webhook payloads."""

    eventType: str
    release: ReleaseInfo
    message: str
    level: str


class RadarrPayload(ArrPayload, total=False):
    """Shape of a Radarr webhook payload."""

    movie: MovieInfo


class SonarrPayload(ArrPayload, total=False):
    """Shape of a Sonarr webhook payload."""

    series: SeriesInfo
    episodes: list[EpisodeInfo]
