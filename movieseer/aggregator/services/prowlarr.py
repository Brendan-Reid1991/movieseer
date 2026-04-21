"""Prowlarr API v1 client."""

from __future__ import annotations

import asyncio
from typing import Literal, TypedDict

from movieseer.aggregator.services.base import _ArrClient
from movieseer.config import PROWLARR_API_KEY, PROWLARR_URL


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


class ProwlarrClient(_ArrClient):
    """Prowlarr API v1 client.

    Constructs and owns its httpx.AsyncClient. Call ``aclose()`` (or use via
    the Aggregator's lifespan) to release connections on shutdown.

    Example
    -------
    prowlarr = ProwlarrClient()
    status = await prowlarr.status()
    indexers = await prowlarr.indexers()
    await prowlarr.aclose()
    """

    _API_PREFIX = "/api/v1"

    def __init__(self) -> None:
        super().__init__(PROWLARR_URL, PROWLARR_API_KEY)

    async def indexers(self) -> list[IndexerDetail]:
        """Return per-indexer status joined from /indexer and /indexerstatus.

        Fetches both endpoints concurrently and joins on indexer ID so each
        result carries both the static config (name, protocol, enabled) and
        the current failure state.

        Raises
        ------
        httpx.HTTPStatusError
            If either API call returns a non-2xx response.
        """
        failing_raw, all_raw = await asyncio.gather(
            self._get("/indexerstatus"),
            self._get("/indexer"),
        )

        # Build a map of indexer_id → error message for fast lookup
        failing_map: dict[int, str] = {
            i["indexerId"]: i.get("message", "")
            for i in failing_raw  # type: ignore[union-attr]
        }

        result: list[IndexerDetail] = []
        for idx in all_raw:  # type: ignore[union-attr]
            idx_id: int = idx["id"]
            protocol_raw: str = idx.get("protocol", "usenet").lower()
            protocol: Literal["usenet", "torrent"] = (
                "torrent" if protocol_raw == "torrent" else "usenet"
            )
            failing = idx_id in failing_map
            result.append(
                IndexerDetail(
                    id=idx_id,
                    name=idx.get("name", "?"),
                    protocol=protocol,
                    enabled=idx.get("enable", True),
                    failing=failing,
                    error=failing_map[idx_id] if failing else None,
                )
            )

        return result

    async def status(self) -> ProwlarrStatus:
        """Query Prowlarr for indexer health.

        Delegates to ``indexers()`` for the actual fetch so both methods
        share a single pair of API calls.

        Raises
        ------
        httpx.HTTPStatusError
            If either API call returns a non-2xx response.
        """
        all_indexers = await self.indexers()
        failing = [i for i in all_indexers if i["failing"]]
        return ProwlarrStatus(
            total=len(all_indexers),
            failing=len(failing),
            healthy=len(all_indexers) - len(failing),
            issues=[
                ProwlarrIssue(name=i["name"], message=i.get("error") or "")
                for i in failing
            ],
            indexers=all_indexers,
        )
