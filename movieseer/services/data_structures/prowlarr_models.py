from typing import Literal, TypedDict


class ProwlarrIssue(TypedDict):
    """A single health-check issue reported by Prowlarr."""

    name: str
    message: str


class IndexerDetail(TypedDict, total=False):
    """Per-indexer status joined from /indexer and /indexerstatus."""

    id: int
    name: str
    protocol: Literal["usenet", "torrent"]
    enabled: bool
    failing: bool
    error: str | None  # message from /indexerstatus if failing, else None


class ProwlarrStatus(TypedDict):
    """Aggregated indexer health from Prowlarr."""

    total: int
    failing: int
    healthy: int
    issues: list[ProwlarrIssue]
    indexers: list[IndexerDetail]
