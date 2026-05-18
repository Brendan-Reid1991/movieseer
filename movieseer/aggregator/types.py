from __future__ import annotations

from typing import Literal, TypedDict

from movieseer.services.data_structures.prowlarr_models import ProwlarrStatus
from movieseer.services.data_structures.sabnzbd_models import Queue, ServerStat


class ServiceError(TypedDict):
    """Uniform error envelope used when a service call fails."""

    error: str


class SystemStatus(TypedDict):
    """Combined system status across all download clients and indexers."""

    prowlarr: ProwlarrStatus | ServiceError
    sabnzbd: Queue | ServiceError


class _ArrStatusBase(TypedDict):
    """Shared required fields for Radarr/Sonarr item status."""

    status: str
    error: str | None


class ArrStatus(_ArrStatusBase, total=False):
    """Full Radarr/Sonarr item status, including optional episode fields."""

    at: str | None
    episodes_queued: int
    episodes: str | None


class HistoryEvent(TypedDict):
    """A single past event in the lifecycle of a media request."""

    event: str
    at: str | None
    source: str
    error: str | None


class RequestItem(TypedDict):
    """Full status snapshot for a single media request."""

    id: int | None
    title: str
    type: Literal["movie", "tv"]
    source: Literal["jellyseerr", "radarr", "sonarr"]
    requested_by: str
    requested_at: str | None
    jellyseerr_status: str | None
    arr: ArrStatus | None
    history: list[HistoryEvent]


class InfraStatus(TypedDict):
    """Response shape for GET /api/infra — indexer and server stats."""

    prowlarr: ProwlarrStatus | ServiceError
    sabnzbd_servers: list[ServerStat] | ServiceError


class StatusResult(TypedDict):
    """Top-level aggregated result returned by the Aggregator."""

    system: SystemStatus | ServiceError
    requests: list[RequestItem]
