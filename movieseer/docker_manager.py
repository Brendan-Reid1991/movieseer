"""
Docker socket integration for Movieseer.

Provides container status listing and service control (restart, rebuild,
stop, start) via the Python Docker SDK. All bulk operations exclude the
Movieseer container itself to prevent self-termination.

Rebuild strategy (Option B): pull the latest image for each container, then
restart. This avoids mounting the compose file or shelling out. It is not a
true ``force-recreate`` but covers the common case of picking up a new image.
"""

import logging
from datetime import UTC
from typing import Any

import docker
import docker.errors

logger = logging.getLogger(__name__)

SELF_NAME = "movieseer"


def _client() -> docker.DockerClient:
    """
    Return a Docker client connected to the local socket.

    Raises
    ------
    RuntimeError
        If the Docker socket is not accessible.
    """
    try:
        return docker.from_env()
    except docker.errors.DockerException as exc:
        raise RuntimeError(f"Cannot connect to Docker socket: {exc}") from exc


def list_containers() -> list[dict[str, Any]]:
    """
    Return status information for all containers known to Docker.

    Each entry contains the container name, current status, and uptime string.
    Containers are sorted alphabetically by name.

    Returns
    -------
    list[dict[str, Any]]
        List of dicts with keys: ``name``, ``status``, ``uptime``.
    """
    client = _client()
    results = []

    for container in client.containers.list(all=True):
        name = container.name
        status = container.status

        container.reload()
        started_at = container.attrs.get("State", {}).get("StartedAt", "")
        uptime = _format_uptime(started_at) if status == "running" else status

        results.append({"name": name, "status": status, "uptime": uptime})
        logger.debug("Container %s: status=%s uptime=%s", name, status, uptime)

    results.sort(key=lambda c: c["name"])
    return results


def restart_all() -> list[str]:
    """
    Restart every running container except Movieseer itself.

    Returns
    -------
    list[str]
        Names of containers that were restarted.
    """
    client = _client()
    restarted = []

    for container in client.containers.list():
        if container.name == SELF_NAME:
            logger.info("Skipping self (%s) during restart", SELF_NAME)
            continue
        logger.info("Restarting container: %s", container.name)
        container.restart()
        restarted.append(container.name)

    return restarted


def rebuild_all() -> list[str]:
    """
    Pull the latest image for each running container (except self), then restart.

    This is Option B from the design doc: not a true ``force-recreate``, but
    sufficient for picking up new images without needing the compose file
    mounted inside the container.

    Returns
    -------
    list[str]
        Names of containers that were rebuilt.
    """
    client = _client()
    rebuilt = []

    for container in client.containers.list():
        if container.name == SELF_NAME:
            logger.info("Skipping self (%s) during rebuild", SELF_NAME)
            continue

        image_tag = container.attrs.get("Config", {}).get("Image", "")
        if image_tag:
            logger.info("Pulling latest image for %s: %s", container.name, image_tag)
            try:
                client.images.pull(image_tag)
            except docker.errors.APIError as exc:
                logger.warning("Image pull failed for %s: %s", container.name, exc)

        logger.info("Restarting container after pull: %s", container.name)
        container.restart()
        rebuilt.append(container.name)

    return rebuilt


def stop_all() -> list[str]:
    """
    Stop every running container, with Movieseer last.

    Returns the names of containers that were stopped.
    """
    client = _client()
    stopped = []
    self_container = None

    for container in client.containers.list():
        if container.name == SELF_NAME:
            self_container = container
            continue
        logger.info("Stopping container: %s", container.name)
        container.stop()
        stopped.append(container.name)

    if self_container is not None:
        logger.info("Stopping self: %s", SELF_NAME)
        self_container.stop()
        stopped.append(SELF_NAME)

    return stopped


def stop_container(name: str) -> None:
    """Stop a single container by name."""
    client = _client()
    try:
        container = client.containers.get(name)
    except docker.errors.NotFound as exc:
        raise ValueError(f"Container {name!r} not found") from exc
    logger.info("Stopping container: %s", name)
    container.stop()


def start_container(name: str) -> None:
    """
    Start a stopped container by name using the Docker SDK.

    Raises ValueError if the container does not exist.
    """
    client = _client()
    try:
        container = client.containers.get(name)
    except docker.errors.NotFound as exc:
        raise ValueError(f"Container {name!r} not found") from exc
    logger.info("Starting container: %s", name)
    container.start()


def _format_uptime(started_at: str) -> str:
    """
    Convert a Docker ``StartedAt`` ISO timestamp into a human-readable uptime.

    Parameters
    ----------
    started_at : str
        ISO 8601 timestamp string from the Docker container state, e.g.
        ``"2024-01-15T10:30:00.123456789Z"``.

    Returns
    -------
    str
        Uptime string such as ``"3d 2h"``, ``"45m"``, or ``"<1m"``.
    """
    if not started_at:
        return "unknown"

    try:
        # Docker timestamps use nanosecond precision; truncate to microseconds.
        ts = started_at[:26].rstrip("Z") + "+00:00"
        from datetime import datetime

        start = datetime.fromisoformat(ts)
        delta = datetime.now(UTC) - start
        total_seconds = int(delta.total_seconds())

        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60

        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {minutes}m"
        if minutes > 0:
            return f"{minutes}m"
        return "<1m"
    except (ValueError, TypeError) as exc:
        logger.warning("Could not parse StartedAt timestamp '%s': %s", started_at, exc)
        return "unknown"
