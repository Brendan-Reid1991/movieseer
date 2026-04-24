from typing import cast

from movieseer.notifier.types import (
    ArrEvent,
    ArrPayload,
    RadarrPayload,
    Services,
    SonarrPayload,
)
from movieseer.notifier.webhooks import (
    download,
    download_failure,
    grab,
    health,
    import_failure,
    manual_interaction_required,
)


async def _dispatch(payload: ArrPayload, service: Services) -> None:
    """Given a payload from either Radarr or Sonarr, dispatch to the appropriate handler
    based on the event type."""
    label = labeller(payload, service)
    match payload.get("eventType", ""):
        case ArrEvent.Grab:
            await grab(payload, label)
        case ArrEvent.Download:
            await download(label)
        case ArrEvent.DownloadFailure:
            await download_failure(payload, label)
        case ArrEvent.ImportFailure:
            await import_failure(payload, label)
        case ArrEvent.ManualInteractionRequired:
            await manual_interaction_required(payload, label)
        case ArrEvent.Health:
            await health(payload, service)
        case _ as unknown:
            raise ValueError(f"Unknown event type: {unknown}")


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
