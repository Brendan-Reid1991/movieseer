# Movieseer

## Structure
```
movieseer/
  docker-compose.yml          # Root compose file, imports all services
  .env                        # Environment variables (not version controlled)
  start.sh                    # macOS startup script (Tailscale, Docker, Jellyfin, containers)
  services/                   # Individual service definitions
    qbittorrent.yml
    sonarr.yml
    radarr.yml
    prowlarr.yml
    flaresolverr.yml
    jellyseerr.yml
    homepage.yml
    sabnzbd.yml
    gluetun.yml
    jellyfin.yml              # Not included in docker-compose.yml — kept for future Linux migration
    config/                   # Service configs (not version controlled)
  scripts/
    jellyfin-proxy/           # Legacy — no longer used
```

## Prerequisites
- Docker Desktop (not Colima — see notes below)
- Docker Compose v2.20+
- Jellyfin macOS app installed (runs natively for VideoToolbox hardware transcoding)
- Media volume mounted at `/Volumes/Jobsworth/media` with `movies/`, `tv/`, and `extra/` subdirectories

## Setup
1. Copy `.env.example` to `.env` and fill in `DATA_PATH`, `PUID`/`PGID`, and API keys
2. Create the Docker network: `docker network create movieseer`
3. Start the stack: `docker compose up -d`
4. Launch the Jellyfin macOS app separately (or use `start.sh` which does all of the above)

## Service URLs
| Service        | URL                      |
|----------------|--------------------------|
| Jellyfin       | http://localhost:8096    |
| Jellyseerr     | http://localhost:5055    |
| Homepage       | http://localhost:3000    |
| Sonarr         | http://localhost:8989    |
| Radarr         | http://localhost:7878    |
| Prowlarr       | http://localhost:9696    |
| qBittorrent    | http://localhost:8080    |
| SABnzbd        | http://localhost:8085    |
| FlareSolverr   | http://localhost:8191    |

## AppleDouble cleanup
The media volume (`/Volumes/Jobsworth`) is formatted as ExFAT. macOS automatically creates `._*` AppleDouble sidecar files on ExFAT volumes (via the SIP-protected `doubleagentd` daemon), which Jellyfin cannot read and which cause `UnauthorizedAccessException` errors during library scans.

This cannot be suppressed at the OS level without reformatting the drive. Instead, a host-level cron job runs every minute to delete them:

```
* * * * * find /Volumes/Jobsworth/media -name "._*" -delete
```

Add with `crontab -e`, verify with `crontab -l`.

## Jellyfin (local macOS app)
Jellyfin runs as a native macOS app rather than a Docker container, giving it direct access to Apple's VideoToolbox framework for hardware-accelerated transcoding (H.264, HEVC, tonemapping). The Docker container image is kept in `services/jellyfin.yml` for future Linux migration but is not included in `docker-compose.yml`.

Jellyseerr and Homepage reach Jellyfin via `host.docker.internal:8096`.

## Common commands
```bash
docker compose up -d          # Start all services
docker compose down           # Stop all services
docker compose pull           # Update all images
docker compose logs -f        # Follow logs
docker compose restart sonarr # Restart a single service
```

## Notes
- **Docker Desktop only** — Colima has virtiofs issues with this setup that cause services to crash on startup with read-only bind mounts
- The `movieseer` Docker network must be created manually before starting the stack; it is declared `external: true` in service files so Compose will not create it automatically
- Jellyfin is not part of the Docker stack on macOS — launch the Jellyfin app directly or via `start.sh`
