import logging
from collections.abc import Awaitable

import httpx

from movieseer.config import NTFY_TOPIC, NTFY_URL

logger = logging.getLogger(__name__)
from movieseer.notifier.types import (
    GrabPayload,
    HealthPayload,
    MessagePayload,
    Priority,
    Services,
)


async def _send_message(
    body: str, title: str, priority: Priority = "default", tags: str = ""
) -> None:
    """POST a push notification to the configured ntfy topic."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{NTFY_URL}/{NTFY_TOPIC}",
                content=body,
                headers={
                    "Title": title,
                    "Priority": priority,
                    "Tags": tags,
                },
            )
    except Exception as e:
        logger.warning("ntfy send failed: %s", e)


def grab(payload: GrabPayload, label: str) -> Awaitable[None]:
    """Notify that a release has been grabbed from an indexer."""
    release = payload.get("release", {})
    indexer = release.get("indexer", "")
    quality = release.get("quality", "")
    body = f"Grabbed from {indexer}" if indexer else "Release grabbed"
    if quality:
        body += f" · {quality}"
    return _send_message(body, f"Grabbed: {label}", priority="low", tags="arrow_down")


def download(label: str) -> Awaitable[None]:
    """Notify that a download has completed and been imported to the library."""
    return _send_message(
        "Download complete, imported to library.",
        f"Available: {label}",
        priority="default",
        tags="white_check_mark",
    )


def download_failure(payload: MessagePayload, label: str) -> Awaitable[None]:
    """Notify that a download failed."""
    msg = payload.get("message", "")
    return _send_message(
        msg or "Download failed.",
        f"Download failed: {label}",
        priority="high",
        tags="x",
    )


def import_failure(payload: MessagePayload, label: str) -> Awaitable[None]:
    """Notify that an import failed."""
    msg = payload.get("message", "")
    return _send_message(
        msg or "Import failed.", f"Import failed: {label}", priority="high", tags="x"
    )


def manual_interaction_required(payload: MessagePayload, label: str) -> Awaitable[None]:
    """Notify that manual intervention is needed."""
    msg = payload.get("message", "")
    return _send_message(
        msg or "Manual action needed.",
        f"Action required: {label}",
        priority="urgent",
        tags="warning",
    )


def health(payload: HealthPayload, service: Services) -> Awaitable[None]:
    """Notify of a health issue reported by Radarr or Sonarr."""
    msg = payload.get("message", "No message provided.")
    level = payload.get("level", "warning").lower()
    priority: Priority = "high" if level == "error" else "default"
    return _send_message(
        msg, f"Health issue from {service}", priority=priority, tags="warning"
    )
