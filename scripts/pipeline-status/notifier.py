import httpx
import os

NTFY_URL = os.getenv("NTFY_URL", "http://ntfy:80")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "movieseer")


async def _send(body: str, title: str, priority: str = "default", tags: str = ""):
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
        print(f"ntfy send failed: {e}")


async def handle_radarr(payload: dict):
    event = payload.get("eventType", "")
    movie = payload.get("movie", {})
    title = movie.get("title", "Unknown")
    year = movie.get("year", "")
    label = f"{title} ({year})" if year else title

    if event == "Grab":
        release = payload.get("release", {})
        indexer = release.get("indexer", "")
        quality = release.get("quality", "")
        body = f"Grabbed from {indexer}" if indexer else "Release grabbed"
        if quality:
            body += f" · {quality}"
        await _send(body, f"Grabbed: {label}", priority="low", tags="arrow_down")

    elif event == "Download":
        await _send("Download complete, imported to library.", f"Available: {label}", priority="default", tags="white_check_mark")

    elif event == "DownloadFailure":
        msg = payload.get("message", "")
        await _send(msg or "Download failed.", f"Download failed: {label}", priority="high", tags="x")

    elif event == "ImportFailure":
        msg = payload.get("message", "")
        await _send(msg or "Import failed.", f"Import failed: {label}", priority="high", tags="x")

    elif event == "ManualInteractionRequired":
        msg = payload.get("message", "")
        await _send(msg or "Manual action needed.", f"Action required: {label}", priority="urgent", tags="warning")

    elif event == "Health":
        msg = payload.get("message", "")
        level = payload.get("level", "warning").lower()
        priority = "high" if level == "error" else "default"
        await _send(msg, "Radarr health issue", priority=priority, tags="warning")


async def handle_sonarr(payload: dict):
    event = payload.get("eventType", "")
    series = payload.get("series", {})
    title = series.get("title", "Unknown")
    episodes = payload.get("episodes", [])
    ep_label = ""
    if episodes:
        ep = episodes[0]
        ep_label = f" S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d}"

    label = f"{title}{ep_label}"

    if event == "Grab":
        release = payload.get("release", {})
        indexer = release.get("indexer", "")
        body = f"Grabbed from {indexer}" if indexer else "Release grabbed"
        await _send(body, f"Grabbed: {label}", priority="low", tags="arrow_down")

    elif event == "Download":
        await _send("Episode imported to library.", f"Available: {label}", priority="default", tags="white_check_mark")

    elif event == "DownloadFailure":
        msg = payload.get("message", "")
        await _send(msg or "Download failed.", f"Download failed: {label}", priority="high", tags="x")

    elif event == "ImportFailure":
        msg = payload.get("message", "")
        await _send(msg or "Import failed.", f"Import failed: {label}", priority="high", tags="x")

    elif event == "ManualInteractionRequired":
        msg = payload.get("message", "")
        await _send(msg or "Manual action needed.", f"Action required: {label}", priority="urgent", tags="warning")

    elif event == "Health":
        msg = payload.get("message", "")
        level = payload.get("level", "warning").lower()
        priority = "high" if level == "error" else "default"
        await _send(msg, "Sonarr health issue", priority=priority, tags="warning")
