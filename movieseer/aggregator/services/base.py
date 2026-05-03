"""Base HTTP client classes for all service integrations."""

from __future__ import annotations

from typing import ClassVar

import httpx


class _BaseServiceClient:
    """Owns an httpx.AsyncClient and provides generic HTTP helpers.

    Has no knowledge of auth — subclasses are responsible for configuring
    authentication at construction time or per-request.

    Subclasses declare ``_API_PREFIX`` to centralise the API version string
    (e.g. ``"/api/v3"``). All ``_get`` and ``_post`` paths are relative to
    that prefix, so an API version bump is a single-line change per service.
    """

    BASE_URL: ClassVar[str]
    _API_PREFIX: ClassVar[str]

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers=headers or {},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client and release connections."""
        await self._client.aclose()

    async def _get(
        self,
        path: str,
        params: dict[str, str | int | bool] | None = None,
    ) -> dict[str, object] | list[object]:
        """Issue a GET request and return the parsed JSON response."""
        r = await self._client.get(f"{self._API_PREFIX}{path}", params=params)
        r.raise_for_status()
        return r.json()

    async def _post(
        self,
        path: str,
        data: dict[str, str] | None = None,
    ) -> None:
        """Issue a POST request. Response body is discarded."""
        r = await self._client.post(f"{self._API_PREFIX}{path}", data=data)
        r.raise_for_status()


class _ArrClient(_BaseServiceClient):
    """Base client for arr-compatible services (Radarr, Sonarr, Prowlarr, etc.).

    Bakes the X-Api-Key header into the underlying httpx.AsyncClient so that
    all requests inherit it automatically — no per-request auth handling needed.

    Adding support for a new arr service requires:

        class NewArrClient(_ArrClient):
            _API_PREFIX = "/api/vN"

            def __init__(self) -> None:
                super().__init__(NEW_ARR_URL, NEW_ARR_API_KEY)
    """

    def __init__(self) -> None:
        super().__init__(headers={"X-Api-Key": self.API_KEY})
