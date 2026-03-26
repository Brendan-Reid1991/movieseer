"""Prowlarr API v1 client."""

from __future__ import annotations

import asyncio
from typing import TypedDict

from movieseer.aggregator.services.base import _ArrClient
from movieseer.config import PROWLARR_API_KEY, PROWLARR_URL


class ProwlarrIssue(TypedDict):
    """A single health-check issue reported by Prowlarr."""

    name: str
    message: str


class ProwlarrStatus(TypedDict):
    """Aggregated indexer health from Prowlarr."""

    total: int
    failing: int
    healthy: int
    issues: list[ProwlarrIssue]


class ProwlarrClient(_ArrClient):
    """Prowlarr API v1 client.

    Constructs and owns its httpx.AsyncClient. Call ``aclose()`` (or use via
    the Aggregator's lifespan) to release connections on shutdown.

    Example
    -------
    prowlarr = ProwlarrClient()
    status = await prowlarr.status()
    await prowlarr.aclose()
    """

    _API_PREFIX = "/api/v1"

    def __init__(self) -> None:
        super().__init__(PROWLARR_URL, PROWLARR_API_KEY)

    async def status(self) -> ProwlarrStatus:
        """Query Prowlarr for indexer health.

        Issues two concurrent requests — one for failing indexers, one for
        the full indexer list — and combines them into a ProwlarrStatus.

        Raises
        ------
        httpx.HTTPStatusError
            If either API call returns a non-2xx response.
        """
        failing_raw, all_raw = await asyncio.gather(
            self._get("/indexerstatus"),
            self._get("/indexer"),
        )
        failing: list[dict[str, str]] = failing_raw  # type: ignore[assignment]
        total = len(all_raw)  # type: ignore[arg-type]
        return ProwlarrStatus(
            total=total,
            failing=len(failing),
            healthy=total - len(failing),
            issues=[
                ProwlarrIssue(
                    name=i.get("indexerName", "?"),
                    message=i.get("message", ""),
                )
                for i in failing
            ],
        )
