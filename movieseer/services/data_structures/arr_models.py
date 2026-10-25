"""Shared Pydantic models and types for arr API clients (Radarr, Sonarr, Prowlarr)."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import Field

from ._base import _CamelBase

type QueueStatus = Literal[
    "queued",
    "paused",
    "downloading",
    "completed",
    "failed",
    "warning",
    "delay",
    "downloadClientUnavailable",
    "fallback",
]

type ArrHistoryEventType = Literal[
    "unknown",
    "grabbed",
    "downloadFolderImported",
    "downloadFailed",
    "downloadIgnored",
]
"""Event types common to all arr history endpoints.

Verified against Radarr/Sonarr source enums. Service-specific types
(MovieHistoryEventType, EpisodeHistoryEventType) extend this via |.
"""


class Language(_CamelBase):
    """A language tag as returned by Radarr/Sonarr."""

    id: int
    name: str


class QualityInfo(_CamelBase):
    """The inner quality object describing a specific quality profile."""

    name: str
    resolution: int


class Quality(_CamelBase):
    """Wraps QualityInfo as returned by the arr quality model."""

    quality: QualityInfo


class StatusMessage(_CamelBase):
    """A single status message entry from a queue record's statusMessages list."""

    messages: list[str] = Field(default_factory=list)


class ArrQueueEntry(_CamelBase):
    """Shared fields across Radarr and Sonarr queue records.

    The aggregator's helpers (_arr_queue_status, _resolve_download) operate
    exclusively on these fields and accept this type directly.
    """

    languages: list[Language] = Field(default_factory=list)
    quality: Quality
    size: float
    sizeleft: float = 0.0
    title: str
    estimated_completion_time: datetime | None = None
    added: datetime | None = None
    status: QueueStatus
    tracked_download_status: str = "Ok"
    status_messages: list[StatusMessage] = Field(default_factory=list)
    error_message: str | None = None
    download_id: str | None = None
    download_client: str | None = None
    indexer: str | None = None


ArrEventT = TypeVar("ArrEventT", bound=str)


class ArrHistoryEntry(_CamelBase, Generic[ArrEventT]):
    """Shared fields across Radarr and Sonarr history records.

    The aggregator's helpers (_arr_history_status, _format_history) operate
    exclusively on these fields and accept this type directly.
    """

    id: int
    source_title: str
    languages: list[Language] = Field(default_factory=list)
    quality: Quality
    quality_cutoff_not_met: bool
    date: datetime
    download_id: str | None = None
    event_type: ArrEventT
    data: dict[str, str | None] = Field(default_factory=dict)
