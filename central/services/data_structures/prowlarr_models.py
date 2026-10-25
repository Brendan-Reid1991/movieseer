from typing import Literal

from pydantic import Field

from ._base import _CamelBase


class ProwlarrIssue(_CamelBase):
    """A single health-check issue reported by Prowlarr."""

    name: str
    message: str


class ProwlarrIndexer(_CamelBase):
    """Per-indexer status joined from /indexer and /indexerstatus."""

    id: int
    name: str
    protocol: Literal["usenet", "torrent"]
    enabled: bool = Field(alias="enable")
    failing: bool
    error: str | None


class ProwlarrStatus(_CamelBase):
    """Aggregated indexer health from Prowlarr."""

    total: int
    failing: int
    healthy: int
    issues: list[ProwlarrIssue]
    indexers: list[ProwlarrIndexer]
