from typing import cast
import logging
from movieseer.notifier.types import (
    ArrPayload,
    ArrWebhookEvent,
    RadarrPayload,
    Services,
    SonarrPayload,
)
from movieseer.notifier.webhooks import Dispatcher

logger = logging.getLogger(__name__)


async def _dispatch(payload: ArrPayload, service: Services) -> None:
    """Given a payload from either Radarr or Sonarr, dispatch to the appropriate handler
    based on the event type."""
    dispatch = Dispatcher()
    label = labeller(payload, service)
    match payload.get("eventType", ""):
        case ArrWebhookEvent.Grab:
            await dispatch.grab(payload, label)
            logger.info("%s ||  Grabbed: %s", service, label)
        case ArrWebhookEvent.Download:
            await dispatch.download(label)
            logger.info("%s ||  Download beginning: %s", service, label)
        case ArrWebhookEvent.DownloadFailure:
            await dispatch.download_failure(payload, label)
            logger.info("%s ||  Download failure: %s", service, label)
        case ArrWebhookEvent.ImportFailure:
            await dispatch.import_failure(payload, label)
            logger.info("%s ||  Import failure: %s", service, label)
        case ArrWebhookEvent.ManualInteractionRequired:
            await dispatch.manual_interaction_required(payload, label)
            logger.info("%s ||  Manual interaction required: %s", service, label)
        case ArrWebhookEvent.Health:
            await dispatch.health(payload, service)
            logger.info("%s ||  Broadcasting health status.", service)
        case "Test":
            await dispatch.test_webhook(payload, service)
            logger.info("%s ||  Webhook test.", service)
        case _ as unknown:
            logger.debug("Skipping unknown event type: %s", unknown)
            


async def handle_radarr(payload: RadarrPayload) -> None:
    """Parse a Radarr webhook payload and dispatch a push notification for the event."""
    await _dispatch(payload, "radarr")


async def handle_sonarr(payload: SonarrPayload) -> None:
    """Parse a Sonarr webhook payload and dispatch a push notification for the event."""
    await _dispatch(payload, "sonarr")


def labeller(payload: ArrPayload, service: Services) -> str:
    """Generate an appropriate label given the payload from either Sonarr or Radarr.

    For Radarr, generates a "{title} ({year})" string.

    For Sonarr, generates a "{series title} S{season number}E{episode number}"
    if the season and episode are available, else it defaults to just the series title.

    Parameters
    ----------
    payload : ArrPayload
        A payload from either a Radarr or Sonarr webhook.
    service : Services
        The service the payload originated from, either "radarr" or "sonarr".

    Returns
    -------
    str
        A formatted label string to be used in notifications for this payload.
    """
    match service:
        case "radarr":
            payload = cast("RadarrPayload", payload)
            movie = payload.get("movie", {})
            title = movie.get("title", "Unknown")
            year = movie.get("year", 0)
            return f"{title} ({year})" if year else title
        case "sonarr":
            payload = cast("SonarrPayload", payload)
            series = payload.get("series", {})
            title = series.get("title", "Unknown")
            episodes = payload.get("episodes", [])
            ep_label = ""
            if episodes:
                ep = episodes[0]
                ep_label = f" S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d}"
            return f"{title}{ep_label}"
