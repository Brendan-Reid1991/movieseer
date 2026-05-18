from typing import Any, Literal
from warnings import warn

from .client_api import _BaseClient

warn(
    """ntfy has been removed from the server as of 2026/05/18. 
    NtfyClient, as well as environment variables, are not currently supported or maintained.""",
    stacklevel=2,
)

Priority = Literal["low", "default", "high", "urgent"]

NTFY_URL = None
NTFY_TOPIC = None


class NtfyClient(_BaseClient):
    """A client for NTFY - pushing notifications to external devices."""

    SERVICE_URL = NTFY_URL

    async def _post(self, content: str, headers: dict[str, Any]):
        """Issue a POST request"""
        r = await self._client.post(
            f"{self._active_url}/{NTFY_TOPIC}", content=content, headers=headers
        )
        r.raise_for_status()
        return r.json()

    async def send_message(
        self,
        msg_body: str,
        title: str | None = None,
        priority: Priority | None = None,
        tags: str | None = None,
    ) -> None:
        return await self._post(
            content=msg_body,
            headers={
                "Title": title or "",
                "Priority": priority or "default",
                "Tags": tags or "",
            },
        )
