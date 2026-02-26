# Movieseer

## Structure
```
movieseer/
  docker-compose.yml          # Root compose file, imports all services
  .env                        # Environment variables (not version controlled)
  services/                   # Individual service definitions
    jellyfin.yml
    jellyfin-proxy.yml        # Reverse proxy in front of Jellyfin (see below)
    qbittorrent.yml
    sonarr.yml
    radarr.yml
    radarr-extra.yml
    prowlarr.yml
    flaresolverr.yml
    jellyseerr.yml
    homepage.yml
    sabnzbd.yml
    gluetun.yml
    config/                   # Service configs (not version controlled)
  scripts/
    jellyfin-proxy/           # Source for the jellyfin-proxy Docker image
      proxy.py
      Dockerfile
```

## Prerequisites
- Docker Desktop (not Colima — see notes below)
- Docker Compose v2.20+
- Media volume mounted at `/Volumes/Jobsworth/media` with `movies/`, `tv/`, and `extra/` subdirectories

## Setup
1. Copy `.env.example` to `.env` and fill in `DATA_PATH`, `PUID`/`PGID`, and API keys
2. Create the Docker network: `docker network create movieseer`
3. Start the stack: `docker compose up -d --build`

> The `--build` flag is required on first run to build the `jellyfin-proxy` image locally.

## Service URLs
| Service        | URL                      |
|----------------|--------------------------|
| Jellyfin       | http://localhost:8096    |
| Jellyseerr     | http://localhost:5055    |
| Homepage       | http://localhost:3000    |
| Sonarr         | http://localhost:8989    |
| Radarr         | http://localhost:7878    |
| Radarr (extra) | http://localhost:7879    |
| Prowlarr       | http://localhost:9696    |
| qBittorrent    | http://localhost:8080    |
| SABnzbd        | http://localhost:8085    |
| FlareSolverr   | http://localhost:8191    |

## Jellyfin Proxy
Jellyfin is not exposed directly. A lightweight Python reverse proxy (`jellyfin-proxy`) sits in front of it on port 8096 and intercepts library scan requests (`POST /Library/Refresh` and `POST /ScheduledTasks/Running/`) to run `find /media -name '._*' -delete` before the scan executes.

This is necessary because the media volume (`/Volumes/Jobsworth`) is formatted as ExFAT, which causes macOS to create `._` AppleDouble sidecar files that Jellyfin cannot read, resulting in `UnauthorizedAccessException` errors during library scans.

All other traffic (including video streaming and WebSockets) passes through transparently. The cleanup is logged to `docker logs jellyfin-proxy`.

## Common commands
```bash
docker compose up -d --build      # Start all services (builds jellyfin-proxy)
docker compose down               # Stop all services
docker compose pull               # Update all images
docker compose logs -f            # Follow logs
docker compose restart sonarr     # Restart a single service
docker logs jellyfin-proxy        # Check proxy activity / scan cleanup log
```

## Notes
- **Docker Desktop only** — Colima has virtiofs issues with this setup that cause services to crash on startup with read-only bind mounts
- The `movieseer` Docker network must be created manually before starting the stack; it is declared `external: true` in service files so Compose will not create it automatically
- Jellyfin's internal port (8096) is not bound to the host — only `jellyfin-proxy` exposes it externally. Do not use VSCode's "Open in Browser" on the `jellyfin` container directly
