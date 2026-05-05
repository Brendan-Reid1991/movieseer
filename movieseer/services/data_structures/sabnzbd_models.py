"""Pydantic models and types for the SABnzbd API client."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from pydantic import BaseModel, Field


class Slot(BaseModel):
    """A single slot entry from the SABnzbd queue API.

    A subset of the slots entry in https://sabnzbd.org/wiki/configuration/4.5/api#queue
    """

    nzo_id: str
    name: str = Field(alias="filename")
    progress: float = Field(alias="percentage")
    eta: str = Field(alias="timeleft")
    status: str


class Queue(BaseModel):
    """Top-level queue object from the SABnzbd queue API.

    A subset of the queue object from
    https://sabnzbd.org/wiki/configuration/4.5/api#queue
    """

    count: int = Field(alias="noofslots")
    speed: str
    eta: str = Field(alias="timeleft")
    paused: bool
    slots: list[Slot]


class HistorySlot(BaseModel):
    """A single entry from the SABnzbd history API.

    A subset of the slots entry in https://sabnzbd.org/wiki/configuration/4.5/api#history
    """

    nzo_id: str
    name: str
    status: str
    completed: int  # Unix timestamp
    fail_message: str = ""

    @property
    def completed_as_iso(self) -> str:
        return datetime.fromtimestamp(self.completed, tz=UTC).isoformat()


class History(BaseModel):
    """Top-level history object from the SABnzbd history API."""

    count: int = Field(alias="noofslots")
    slots: list[HistorySlot]


class RawServerStat(BaseModel):
    """Per-server entry from the SABnzbd server_stats API.

    articles_tried and articles_success are keyed by date string (YYYY-MM-DD).
    """

    articles_tried: dict[str, int]
    articles_success: dict[str, int]

    @property
    def total_tried(self) -> int:
        """Return the total number of articles tried by the server."""
        return sum(self.articles_tried.values())

    @property
    def total_success(self) -> int:
        """Return the total number of articles successfully downloaded by the server."""
        return sum(self.articles_success.values())

    @property
    def hit_rate(self) -> float:
        """Return the success rate of the server."""
        if self.total_tried == 0:
            return 0.0
        return round(self.total_success / self.total_tried, 4)

    def summarise(self, name: str, ssl: bool) -> ServerStat:
        """Return a summary of this servers performance, given a name and ssl status."""
        return ServerStat(
            name=name,
            ssl=ssl,
            articles_tried=self.total_tried,
            articles_success=self.total_success,
            hit_rate=self.hit_rate,
        )


class ServerStatsData(BaseModel):
    """Top-level response from the SABnzbd server_stats API."""

    servers: dict[str, RawServerStat]


class ServerConfig(BaseModel):
    """A single server entry from the SABnzbd get_config?section=servers API."""

    host: str
    ssl: bool


class ServersConfig(BaseModel):
    """Top-level config object from the SABnzbd get_config?section=servers API."""

    servers: list[ServerConfig]


class ServerStat(TypedDict):
    """Hit-rate statistics for a single SABnzbd news server (cumulative totals)."""

    name: str
    ssl: bool
    articles_tried: int
    articles_success: int
    hit_rate: float
