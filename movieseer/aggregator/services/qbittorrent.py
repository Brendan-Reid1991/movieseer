"""qBittorrent API client."""

from __future__ import annotations

from typing import TypedDict

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
    the session cookie between calls, so ``_login()`` only needs to establish
    a fresh session when the cookie has expired.

    For now ``_login()`` is called before every request (pre-existing
    behaviour). A future improvement can call it once at startup and retry
    on 403.

    Call ``aclose()`` (or use via the Aggregator's lifespan) to release
    connections on shutdown.

    Example
    -------
    qbit = QBittorrentClient()
    summary = await qbit.summary()
    torrents = await qbit.torrents()
    await qbit.aclose()
    """

    _API_PREFIX = "/api/v2"

    def __init__(self) -> None:
        super().__init__(QBITTORRENT_URL)

    async def _login(self) -> None:
        """Authenticate and store the session cookie on the client."""
        await self._post(
            "/auth/login",
            data={"username": QBITTORRENT_USER, "password": QBITTORRENT_PASS},
        )

    async def summary(self) -> QbitSummary:
        """Fetch a count of active and downloading torrents.

        Raises
        ------
        httpx.HTTPStatusError
            If the torrent-info request returns a non-2xx response.
        """
        await self._login()
        data = await self._get("/torrents/info", params={"filter": "active"})
        torrents: list[dict[str, object]] = data  # type: ignore[assignment]
        return QbitSummary(
            active=len(torrents),
            downloading=sum(
                1 for t in torrents if "download" in str(t.get("state", "")).lower()
            ),
        )

    async def torrents(self) -> dict[str, Torrent]:
        """Return all torrents keyed by lowercase info-hash.

        Raises
        ------
        httpx.HTTPStatusError
            If the torrent-info request returns a non-2xx response.
        """
        await self._login()
        data = await self._get("/torrents/info")
        raw: list[dict[str, object]] = data  # type: ignore[assignment]
        return {t["hash"].lower(): Torrent.model_validate(t) for t in raw}  # type: ignore[index]
