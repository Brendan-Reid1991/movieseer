"""Pydantic models for the Jellyseerr API.

The primary dataclass is MediaRequest,
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from ._base import _CamelBase


class User(_CamelBase):
    """Required only to track requests by specific users.

    NOTE: display_name is not in the API schema, but is a
    derived value in the typescript. Unclear if this will be problematic
    down the line."""

    display_name: str = ""


class MediaInfo(_CamelBase):
    """A dataclass replicated the MediaInfo object."""

    tmdb_id: int
    external_service_id: int | None = None
    status: int = 1
    original_title: str | None = None
    title: str | None = None


class MediaRequest(_CamelBase):
    """A dataclass replicating this object:
    https://github.com/Fallenbagel/jellyseerr/blob/main/server/entity/MediaRequest.ts

    """

    id: int
    status: int
    type: Literal["movie", "tv"]
    created_at: datetime
    requested_by: User
    media: MediaInfo


class MediaDetail(_CamelBase):
    """Simple dataclass to capture the title/name of a piece of media."""

    title: str | None = None  # present on movie responses
    name: str | None = None  # present on TV responses
