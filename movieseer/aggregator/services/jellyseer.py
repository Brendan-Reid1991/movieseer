from typing import Literal

from movieseer.aggregator.services.base import _BaseServiceClient
from movieseer.aggregator.services.models.jellyseer_models import (
    MediaDetail,
    MediaRequest,
)
from movieseer.config import JELLYSEERR_API_KEY, JELLYSEERR_URL


class JellyseerClient(_BaseServiceClient):
    """Jellyseer API client.

    Constructs and owns its httpx.AsyncClient. Call ``aclose()`` (or use via
    the Aggregator's lifespan) to release connections on shutdown.

    Example
    -------
    jelly = JellyseerClient()
    requests = await jelly.requests()
    await jelly.aclose()
    """

    _API_PREFIX = "/api/v1"

    def __init__(self) -> None:
        super().__init__(JELLYSEERR_URL, headers={"X-Api-Key": JELLYSEERR_API_KEY})

    async def requests(self, take: int = 10) -> list[MediaRequest]:
        """Get recent requests."""
        data = await self._get("/request", params={"take": take, "sort": "added"})
        return [MediaRequest.model_validate(r) for r in data.get("results", [])]

    async def media_detail(self, media_type: Literal["movie", "tv"], tmdb_id: int) -> MediaDetail:
        """Fetch title metadata for a movie or TV show by TMDB ID."""
        data = await self._get(f"/{media_type}/{tmdb_id}")
        return MediaDetail.model_validate(data)
