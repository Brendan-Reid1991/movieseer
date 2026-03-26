from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from movieseer.aggregator.services.prowlarr import ProwlarrStatus
    from movieseer.aggregator.services.qbittorrent import QbitSummary
    from movieseer.aggregator.services.sabnzbd import Queue


class SystemStatus(TypedDict):
    """Combined system status across all download clients and indexers."""

    prowlarr: ProwlarrStatus | dict[str, str]
    sabnzbd: Queue | dict[str, str]
    qbittorrent: QbitSummary | dict[str, str]


class _ArrStatusBase(TypedDict):
    """Shared required fields for Radarr/Sonarr item status."""

    status: str
    error: str | None


class ArrStatus(_ArrStatusBase, total=False):
    """Full Radarr/Sonarr item status, including optional episode fields."""

    at: str | None
    episodes_queued: int
    episodes: str | None


class DownloadInfo(TypedDict):
    """Details of an active or recent download from any client."""

    client: str
    name: str
    progress: float
    status: str
    eta: str
    error: str | None


class HistoryEvent(TypedDict):
    """A single past event in the lifecycle of a media request."""

    event: str
    at: str | None
    source: str
    error: str | None


class RequestItem(TypedDict):
    """Full status snapshot for a single Jellyseerr media request."""

    id: int | None
    title: str
    type: str
    source: str
    requested_by: str
    requested_at: str | None
    jellyseerr_status: str | None
    arr: ArrStatus | None
    download: DownloadInfo | None
    history: list[HistoryEvent]


class StatusResult(TypedDict):
    """Top-level aggregated result returned by the Aggregator."""

    system: SystemStatus | dict[str, str]
    requests: list[RequestItem]
