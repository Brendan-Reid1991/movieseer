from typing import Literal

from movieseer.config import SEERR_API_KEY, SEERR_URL

from .client_api import _ApiKeyClient, gateway
from .data_structures.seerr_models import (
    MediaDetail,
    MediaRequest,
)


@gateway("/api/v1")
class SeerrClient(_ApiKeyClient):
    """Seerr API client.

    Constructs and owns its httpx.AsyncClient. Call ``aclose()`` (or use via
    the Aggregator's lifespan) to release connections on shutdown.

    Example
    -------
    seerr = SeerrClient()
    requests = await seerr.requests()
    await seerr.aclose()
    """

    SERVICE_URL = SEERR_URL
    API_KEY = SEERR_API_KEY

    async def requests(self, take: int = 10) -> list[MediaRequest]:
        """Get recent requests."""
        data = await self._get("/request", params={"take": take, "sort": "added"})
        return [MediaRequest.model_validate(r) for r in data.get("results", [])]

    async def media_detail(self, media_type: Literal["movie", "tv"], tmdb_id: int) -> MediaDetail:
        """Fetch title metadata for a movie or TV show by TMDB ID."""
        data = await self._get(f"/{media_type}/{tmdb_id}")
        return MediaDetail.model_validate(data)
