"""Pydantic models for the Jellyseerr API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from movieseer.aggregator.services.models._base import _Base


class User(_Base):
    display_name: str = ""


class MediaInfo(_Base):
    tmdb_id: int
    external_service_id: int | None = None
    status: int = 1
    original_title: str | None = None
    title: str | None = None


class MediaRequest(_Base):
    id: int
    status: int
    type: Literal["movie", "tv"]
    created_at: datetime
    requested_by: User
    media: MediaInfo


class MediaDetail(_Base):
    title: str | None = None  # present on movie responses
    name: str | None = None  # present on TV responses
