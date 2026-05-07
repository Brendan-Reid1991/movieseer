import logging
from collections.abc import Awaitable

from movieseer.notifier.types import GrabPayload, HealthPayload, MessagePayload, Priority, Services
from movieseer.services import NtfyClient

logger = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, url: str | None = None):
        self.client = NtfyClient(url=url)

    def grab(self, payload: GrabPayload, label: str) -> Awaitable[None]:
        """Notify that a release has been grabbed from an indexer."""
        release = payload.get("release", {})
        indexer = release.get("indexer", "")
        quality = release.get("quality", "")
        body = f"Grabbed from {indexer}" if indexer else "Release grabbed"
        if quality:
            body += f" · {quality}"
        return self.client.send_message(
            body, f"Grabbed: {label}", priority="low", tags="arrow_down"
        )

    def download(self, label: str) -> Awaitable[None]:
        """Notify that a download has completed and been imported to the library."""
        return self.client.send_message(
            "Download complete, imported to library.",
            f"Available: {label}",
            priority="default",
            tags="white_check_mark",
        )

    def download_failure(self, payload: MessagePayload, label: str) -> Awaitable[None]:
        """Notify that a download failed."""
        msg = payload.get("message", "")
        return self.client.send_message(
            msg or "Download failed.",
            f"Download failed: {label}",
            priority="high",
            tags="x",
        )

    def import_failure(self, payload: MessagePayload, label: str) -> Awaitable[None]:
        """Notify that an import failed."""
        msg = payload.get("message", "")
        return self.client.send_message(
            msg or "Import failed.", f"Import failed: {label}", priority="high", tags="x"
        )

    def manual_interaction_required(self, payload: MessagePayload, label: str) -> Awaitable[None]:
        """Notify that manual intervention is needed."""
        msg = payload.get("message", "")
        return self.client.send_message(
            msg or "Manual action needed.",
            f"Action required: {label}",
            priority="urgent",
            tags="warning",
        )

    def health(self, payload: HealthPayload, service: Services) -> Awaitable[None]:
        """Notify of a health issue reported by Radarr or Sonarr."""
        msg = payload.get("message", "No message provided.")
        level = payload.get("level", "warning").lower()
        priority: Priority = "high" if level == "error" else "default"
        return self.client.send_message(
            msg, f"Health issue from {service}", priority=priority, tags="warning"
        )

    def test_webhook(self, payload: MessagePayload, service: Services) -> Awaitable[None]:
        return self.client.send_message(
            payload.get("message", "No message provided."),
            f"Webhook test from {service}",
            tags="test",
        )
