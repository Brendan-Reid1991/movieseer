"""qBittorrent API client."""

from __future__ import annotations

from typing import TypedDict, cast

import httpx
from pydantic import BaseModel

from movieseer.aggregator.services.base import _BaseServiceClient
from movieseer.config import QBITTORRENT_PASS, QBITTORRENT_URL, QBITTORRENT_USER


class QbitSummary(TypedDict):
    """Aggregated qBittorrent torrent counts."""

    active: int
    downloading: int


class Torrent(BaseModel):
    """A single torrent entry from the qBittorrent API."""

    hash: str
    name: str
    state: str
    progress: float
    eta: int
    size: int


class QBittorrentClient(_BaseServiceClient):
    """qBittorrent Web API client.

    Constructs and owns its httpx.AsyncClient. The long-lived client retains
    the session cookie across calls; login is performed once on first use and
    retried automatically on 403.

    Call ``aclose()`` (or use via the Aggregator's lifespan) to release
    connections on shutdown.

    Example
    -------
    qbit = QBittorrentClient()
    summary = await qbit.summary()
    torrents = await qbit.torrents()
    await qbit.aclose()
    """

    BASE_URL = QBITTORRENT_URL
    _API_PREFIX = "/api/v2"

    def __init__(self) -> None:
        super().__init__()
        self._authenticated = False

    async def _login(self) -> None:
        """Authenticate and store the session cookie on the client."""
        await self._post(
            "/auth/login",
            data={"username": QBITTORRENT_USER, "password": QBITTORRENT_PASS},
        )
        self._authenticated = True

    async def _ensure_authenticated(self) -> None:
        if not self._authenticated:
            await self._login()

    async def _get_authenticated(
        self, path: str, params: dict[str, str | int | bool] | None = None
    ) -> dict[str, object] | list[object]:
        """Issue a GET request, re-authenticating once on 403."""
        await self._ensure_authenticated()
        try:
            return await self._get(path, params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                self._authenticated = False
                await self._login()
                return await self._get(path, params)
            raise

    async def summary(self) -> QbitSummary:
        """Fetch a count of active and downloading torrents."""
        data = cast(
            "list[dict[str, object]]",
            await self._get_authenticated("/torrents/info", params={"filter": "active"}),
        )
        return QbitSummary(
            active=len(data),
            downloading=sum(1 for t in data if "download" in str(t.get("state", "")).lower()),
        )

    async def torrents(self) -> dict[str, Torrent]:
        """Return all torrents keyed by lowercase info-hash."""
        data = cast(
            "list[dict[str, object]]",
            await self._get_authenticated("/torrents/info"),
        )
        return {str(t["hash"]).lower(): Torrent.model_validate(t) for t in data}
