"""Base HTTP client classes for all service integrations."""

from __future__ import annotations

from typing import ClassVar

import httpx


def gateway(url: str):
    """Decorator to populate _BaseClient subclasses with an _API_PREFIX
    class variable.

    Added solely to avoid muddying the subclass definitions.
    """

    def decorator(cls: type[_BaseClient]):
        cls._API_PREFIX = url
        return cls

    return decorator


class _BaseClient:
    """Base class for all API calls to client services.

    Subclasses inherit and populate the `SERVICE_URL` variable which comes from
    the config.py.

    _API_PREFIX can be set in the class body, or via the @gateway decorator.
    """

    SERVICE_URL: ClassVar[str]
    _API_PREFIX: ClassVar[str] = ""

    def __init__(
        self,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._active_url = url or self.SERVICE_URL
        self._client = httpx.AsyncClient(
            base_url=self._active_url,
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


class _ApiKeyClient(_BaseClient):
    """Base client for services that accept the API key via the header.

    Bakes the X-Api-Key header into the underlying httpx.AsyncClient so that
    all requests inherit it automatically.
    """

    API_KEY: ClassVar[str]

    def __init__(self, url: str | None = None) -> None:
        super().__init__(url=url, headers={"X-Api-Key": self.API_KEY})
