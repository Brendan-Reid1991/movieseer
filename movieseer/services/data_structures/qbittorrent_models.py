from typing import TypedDict

from pydantic import BaseModel


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
