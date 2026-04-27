# Movieseer

A self-hosted media server built on the *arr stack, with a bespoke FastAPI dashboard
(`movieseer`) for monitoring and control.

## Structure
```
movieseer/
  services/                   # Individual service definitions
    ...
    config/                   # Service configs (not version controlled)
  movieseer/                  # Python application source
    main.py                   # FastAPI app — routes, SSE stream, lifespan
    config.py                 # All env var reads centralised here
    aggregator/               # Polls Radarr, Sonarr, Prowlarr, SABnzbd, qBittorrent, Jellyseerr
    notifier/                 # Push notifications via ntfy on Radarr/Sonarr webhook events
    event_log/                # SQLite-backed activity log; streamed to the dashboard via SSE
    docker_manager.py         # Docker SDK wrapper (list, restart, rebuild, stop containers)
    templates/index.html      # Dashboard HTML shell
  scripts/
    setup_webhooks.py         # Registers Radarr/Sonarr webhooks pointing at Movieseer
    get_apis.py               # Reads API keys from service config files (work in progress)
    logs.sh                   # Formatted log viewer for Radarr and Sonarr (colour-coded, live tail)
    set-vpn.sh                # Writes a new active.env from a VPN config in vpn_configurations/
  vpn_configurations/         # WireGuard configs for Gluetun; active.env is the live config
```

## The Movieseer dashboard

`movieseer` is a FastAPI service that exposes a web dashboard and a set of JSON/SSE
endpoints. It runs in Docker alongside the rest of the stack.

### Event log

Polls Radarr, Sonarr, SABnzbd, and Prowlarr on a configurable interval
(`EVENT_POLL_INTERVAL`, default 30 s). Signal events (grabs, imports, failures,
indexer state changes) are written to a SQLite database and pushed to connected
dashboard clients via SSE. Retention is configurable (`EVENT_RETENTION_DAYS`,
default 7 days).

### Push notifications

Radarr and Sonarr webhook payloads are dispatched as push notifications via a
self-hosted [ntfy](https://ntfy.sh) instance. Notifications are sent for: grab,
download, download failure, import failure, manual interaction required, and health
events. The ntfy topic is `movieseer` by default; to change it, update `NTFY_TOPIC`
in `services/movieseer.yml`.

## Prerequisites

- Docker Desktop (not Colima — see notes below)
- Docker Compose v2.20+
- [Tailscale](https://tailscale.com) — installed and authenticated (`start.sh` starts
  it automatically, but it must already be set up)
- Media volume mounted and appropriately set in .env. 

## Setup

1. Copy `.env.example` to `.env` and fill in the variables.
2. Create the Docker network: `docker network create movieseer` — skip this if you use
   `./start.sh`, which creates it automatically
3. Start the stack: `docker compose up -d` (or `./start.sh`, which also checks the
   media volume, starts Tailscale and Docker Desktop, and waits for services to
   become healthy)
4. Register Radarr/Sonarr webhooks: `python3 scripts/setup_webhooks.py`

### Key environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_PATH` | — | Host path for media storage |
| `MEDIA_MOUNT` | `/data` | Container mount point for `DATA_PATH` |
| `HOST_IP` | `localhost` | Tailscale or LAN IP — used for browser-facing links |
| `PUID` / `PGID` | — | User/group IDs for container file ownership |
| `LOG_PATH` | — | Host path for Movieseer log files |
| `PLEX_CLAIM` | — | Plex claim token (from plex.tv/claim; required only on first container launch) |
| `PLEX_TOKEN` | — | Plex auth token for API calls |
| `NTFY_PORT` | `8095` | Published port for the ntfy container |
| `EVENT_POLL_INTERVAL` | `30` | Seconds between event collector cycles |
| `EVENT_RETENTION_DAYS` | `7` | Days of events to keep in SQLite |
| `CACHE_TTL` | `30` | Seconds before the aggregator cache expires |
| `HISTORY_WINDOW_DAYS` | `7` | Lookback window for direct Radarr/Sonarr activity |
| `MOVIESEER_PORT` | — | Published host port for Movieseer |
| `PLEX_PORT` | `32400` | Published host port for Plex |
| `JELLYFIN_PORT` | `8096` | Published host port for Jellyfin |
| `JELLYSEERR_PORT` | `5055` | Published host port for Jellyseerr |
| `SONARR_PORT` | `8989` | Published host port for Sonarr |
| `RADARR_PORT` | `7878` | Published host port for Radarr |
| `SABNZBD_PORT` | `8085` | Published host port for SABnzbd |
| `QBITTORRENT_PORT` | `8080` | Published host port for qBittorrent |

## Service URLs

> When accessing from another device (e.g. via Tailscale), replace `localhost` with
> your `HOST_IP` value.

| Service | URL |
|---------|-----|
| Movieseer | http://localhost:$MOVIESEER_PORT |
| Jellyfin | http://localhost:8096 |
| Plex | http://localhost:32400 |
| Jellyseerr | http://localhost:5055 |
| Sonarr | http://localhost:8989 |
| Radarr | http://localhost:7878 |
| Prowlarr | http://localhost:9696 |
| qBittorrent | http://localhost:8080 |
| SABnzbd | http://localhost:8085 |
| FlareSolverr | http://localhost:8191 |
| ntfy | http://localhost:$NTFY_PORT |

## Development

Dependencies and tooling are managed with [uv](https://github.com/astral-sh/uv).

```bash
make install       # create venv and sync deps
make test          # run test suite
make lint          # lint with ruff (fixes in place)
make fmt-check     # verify formatting
make ci            # lint + format check + tests
```

Run the app locally outside Docker (load `.env` first so the service URLs and API keys
are available):

```bash
set -a && source .env && set +a
uv run uvicorn movieseer.main:app --reload --port 8099
```

To preview the dashboard without any running services or environment variables, use the
demo app. It serves the same HTML shell and returns synthetic data for all endpoints:

```bash
uv run uvicorn movieseer.demo:app --port 8099
```

## Common commands

```bash
docker compose up -d           # Start all services
docker compose down            # Stop all services
docker compose pull            # Update all images
docker compose logs -f         # Follow logs
docker compose restart sonarr  # Restart a single service
bash scripts/logs.sh           # Colour-coded live tail of Radarr and Sonarr logs
```

## VPN configuration

WireGuard configs for Gluetun live in `vpn_configurations/`. To switch to a different
server:

```bash
bash scripts/set-vpn.sh <config-name>   # e.g. fr-par-wg-002
docker compose restart gluetun
```

This writes the selected config's keys and endpoint to `vpn_configurations/active.env`,
which Gluetun reads on startup.

## Notes

- **Docker Desktop only** — Colima has virtiofs issues with this setup that cause
  services to crash on startup with read-only bind mounts
- The `movieseer` Docker network must be created manually before starting the stack;
  it is declared `external: true` in service files so Compose will not create it
  automatically (`start.sh` does this for you)
- **SABnzbd incomplete directory** — hardcoded to
  `/Users/brendan/Downloads/sabnzbd-incomplete` in `services/sabnzbd.yml`; update
  this if you move to a different machine
- **qBittorrent networking** — qBittorrent uses Gluetun's network namespace; its
  web UI is accessible via Gluetun's published port, not a port of its own



### Movieseer API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Dashboard HTML shell |
| `GET` | `/api/status` | Aggregated status from all services (cached, 30 s TTL) |
| `GET` | `/api/config` | Browser-facing URLs for all services |
| `GET` | `/api/search?q=` | Proxy search to Jellyseerr; returns top 5 results with poster and deep-link |
| `GET` | `/api/containers` | Docker container list with state and uptime |
| `GET` | `/api/storage` | Disk usage for `MEDIA_MOUNT` |
| `GET` | `/api/infra` | Prowlarr indexer health + SABnzbd server hit-rate stats |
| `GET` | `/api/events` | SSE stream — last 25 events on connect, then live updates |
| `POST` | `/webhook/radarr` | Radarr webhook receiver (invalidates cache + dispatches ntfy notification) |
| `POST` | `/webhook/sonarr` | Sonarr webhook receiver (invalidates cache + dispatches ntfy notification) |
| `POST` | `/actions/restart` | Restart all containers except Movieseer |
| `POST` | `/actions/rebuild` | Pull latest images then restart all containers except Movieseer |
| `POST` | `/actions/shutdown` | Stop all containers (Movieseer last) |
| `POST` | `/actions/container/{name}/start` | Start a single stopped container |
| `POST` | `/actions/container/{name}/stop` | Stop a single container |
| `POST` | `/actions/sync-libraries` | Trigger Jellyfin + Plex library refresh, then Jellyseerr sync (progress via SSE) |
