#!/usr/bin/env python3
"""Configure Radarr and Sonarr to send webhook events to the pipeline-status service.

Run once from the project root after the stack is up:
    python3 scripts/setup_webhooks.py
"""

import os
import sys
from pathlib import Path

import httpx


def load_env(path: Path):
    """Minimal .env loader — no external dependencies required."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())
    except FileNotFoundError:
        pass


load_env(Path(__file__).parent.parent / ".env")

# Radarr/Sonarr are accessed from the host on their published ports.
RADARR_HOST = os.getenv("RADARR_HOST", "http://localhost:7878")
RADARR_API_KEY = os.getenv("HOMEPAGE_VAR_RADARR_API_KEY", "")

SONARR_HOST = os.getenv("SONARR_HOST", "http://localhost:8989")
SONARR_API_KEY = os.getenv("HOMEPAGE_VAR_SONARR_API_KEY", "")

# This is the URL Radarr/Sonarr will POST to — must be the internal Docker network address.
PIPELINE_INTERNAL = os.getenv("PIPELINE_STATUS_INTERNAL", "http://pipeline-status:8099")

NOTIFICATION_NAME = "pipeline-status"


def upsert_notification(base_url: str, api_key: str, payload: dict, label: str):
    headers = {"X-Api-Key": api_key}

    r = httpx.get(f"{base_url}/api/v3/notification", headers=headers, timeout=10)
    r.raise_for_status()
    existing = next((n for n in r.json() if n["name"] == NOTIFICATION_NAME), None)

    if existing:
        payload["id"] = existing["id"]
        r = httpx.put(
            f"{base_url}/api/v3/notification/{existing['id']}",
            headers=headers, json=payload, timeout=10,
        )
        print(f"  {label}: updated '{NOTIFICATION_NAME}' (id={existing['id']})")
    else:
        r = httpx.post(
            f"{base_url}/api/v3/notification",
            headers=headers, json=payload, timeout=10,
        )
        print(f"  {label}: created '{NOTIFICATION_NAME}'")

    r.raise_for_status()


def configure_radarr():
    upsert_notification(
        RADARR_HOST, RADARR_API_KEY,
        {
            "name": NOTIFICATION_NAME,
            "onGrab": True,
            "onDownload": True,
            "onUpgrade": False,
            "onRename": False,
            "onMovieAdded": False,
            "onMovieDelete": False,
            "onMovieFileDelete": False,
            "onMovieFileDeleteForUpgrade": False,
            "onHealthIssue": True,
            "onHealthRestored": False,
            "onApplicationUpdate": False,
            "onManualInteractionRequired": True,
            "includeHealthWarnings": True,
            "implementation": "Webhook",
            "implementationName": "Webhook",
            "configContract": "WebhookSettings",
            "tags": [],
            "fields": [
                {"name": "url", "value": f"{PIPELINE_INTERNAL}/webhook/radarr"},
                {"name": "method", "value": 1},
            ],
        },
        "Radarr",
    )


def configure_sonarr():
    upsert_notification(
        SONARR_HOST, SONARR_API_KEY,
        {
            "name": NOTIFICATION_NAME,
            "onGrab": True,
            "onDownload": True,
            "onUpgrade": False,
            "onRename": False,
            "onEpisodeFileDelete": False,
            "onEpisodeFileDeleteForUpgrade": False,
            "onSeriesAdd": False,
            "onSeriesDelete": False,
            "onHealthIssue": True,
            "onHealthRestored": False,
            "onApplicationUpdate": False,
            "onManualInteractionRequired": True,
            "includeHealthWarnings": True,
            "implementation": "Webhook",
            "implementationName": "Webhook",
            "configContract": "WebhookSettings",
            "tags": [],
            "fields": [
                {"name": "url", "value": f"{PIPELINE_INTERNAL}/webhook/sonarr"},
                {"name": "method", "value": 1},
            ],
        },
        "Sonarr",
    )


if __name__ == "__main__":
    if not RADARR_API_KEY or not SONARR_API_KEY:
        print("ERROR: API keys not found in environment or .env file.")
        sys.exit(1)

    print("Configuring webhooks...")
    try:
        configure_radarr()
        configure_sonarr()
    except httpx.HTTPStatusError as e:
        print(f"ERROR: {e.response.status_code} — {e.response.text}")
        sys.exit(1)
    except httpx.ConnectError as e:
        print(f"ERROR: Could not connect — {e}")
        sys.exit(1)

    print("Done. Radarr and Sonarr will now POST events to pipeline-status.")
