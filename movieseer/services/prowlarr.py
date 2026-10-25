"""Prowlarr API v1 client."""

from __future__ import annotations

import asyncio
from typing import cast

from movieseer.config import PROWLARR_API_KEY, PROWLARR_URL

from .client_api import _ApiKeyClient, gateway
from .data_structures.prowlarr_models import ProwlarrIndexer, ProwlarrIssue, ProwlarrStatus


@gateway("/api/v1")
class ProwlarrClient(_ApiKeyClient):
    """Prowlarr API client."""

    SERVICE_URL = PROWLARR_URL
    API_KEY = PROWLARR_API_KEY

    async def indexers(self) -> list[ProwlarrIndexer]:
        """Return per-indexer status joined from /indexer and /indexerstatus.

        - /indexer call gets static information about all indexers in prowlarr
        - /indexerstatus retrieves real time information about the status of the indexers.
            If all indexers are healthy, the return type is an empty list.
            https://github.com/Prowlarr/Prowlarr/blob/develop/src/Prowlarr.Api.V1/Indexers/IndexerStatusController.cs

        We cross reference by indexer ID and return a combined set of information.
        """
        _failing, _all = await asyncio.gather(
            self._get("/indexerstatus"),
            self._get("/indexer"),
        )
        failing_raw = cast("list[dict[str, object]]", _failing)
        all_raw = cast("list[dict[str, object]]", _all)

        # Build a map of indexer_id → error message for fast lookup
        failing_map: dict[int, str] = {i["indexerId"]: i.get("message", "") for i in failing_raw}

        result: list[ProwlarrIndexer] = []
        for indexer in all_raw:
            failing: bool = indexer["id"] in failing_map
            error: str = failing_map.get(indexer["id"], None)

            result.append(
                ProwlarrIndexer.model_validate(indexer | {"failing": failing, "error": error})
            )

        return result

    async def status(self) -> ProwlarrStatus:
        """Get a quick-glance of the current status of Prowlarr indexers.

        Calls `indexers`, so this method also queries the API.

        Raises
        ------
        httpx.HTTPStatusError
            If either API call returns a non-2xx response.
        """
        all_indexers = await self.indexers()
        failing = [i for i in all_indexers if i.failing]
        return ProwlarrStatus(
            total=len(all_indexers),
            failing=len(failing),
            healthy=len(all_indexers) - len(failing),
            issues=[ProwlarrIssue(name=i.name, message=i.error or "") for i in failing],
            indexers=all_indexers,
        )
