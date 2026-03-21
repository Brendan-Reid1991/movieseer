# Movieseer Hub — Design Document

## Overview

`pipeline-status` becomes **Movieseer**: the primary interface for the media stack, replacing Homepage entirely. It serves the dashboard UI, aggregates status from all services, provides Jellyseerr search, and controls Docker services.

---

## Directory Structure

```
movieseer/          ← app source (replaces scripts/pipeline-status/)
  Dockerfile
  main.py
  aggregator.py
  notifier.py
  requirements.txt
  templates/

services/
  movieseer.yml     ← replaces services/pipeline-status.yml
```

---

## Layout

### Top bar
- **Pending requests** counter: requests with status other than "available"
- **Time**
- **Calendar**
- **Search bar**: inline Jellyseerr search, shows top 4–5 results (poster, title, type) with links into Jellyseerr
- Another interesting widget?

### Main "focus"
- "Browse Media" and "Stream Media" which link to jellyseer and -fin respectively, should be larger buttons such that it's immediately obvious what the page is "for

Below this should be "Manage TV Shows" (Sonarr) and "Manage Movies" (Radarr)

### Download Management
- Links to qBittorrent and SABnzbd
- Active downloads with progress, speed, ETA (existing aggregator data)

### Request Management
- Links to Radarr and Sonarr. Keep these links and their names.
- Recent requests with status (existing aggregator data)

### Service Health
- Grid of all containers: name, status (running/stopped/restarting), uptime
- Sourced from Docker socket

### Service Control
- **Restart** — `docker restart` on all containers except self
- **Rebuild** — pull latest image + force-recreate all containers except self

---

## New Integrations

### Docker socket
Mount `/var/run/docker.sock` into the container. Use the Python `docker` SDK to:
- List containers and their status (health section)
- Restart containers individually (restart action)

**Open question — Rebuild approach**: `docker restart` is straightforward via the SDK. Force-recreating containers properly requires `docker compose up --force-recreate`, which means either:
- **(A)** Mount the compose file + docker CLI binary into the container and shell out — messy
- **(B)** For rebuild, only pull new images + restart (not true recreate) — simpler but less powerful
- **(C)** A small host-side shell script triggered via the socket — cleaner separation

### Jellyseerr search
New endpoint `GET /api/search?q=<query>` that proxies to Jellyseerr's `/api/v1/search`, returns top 5 results with title, type, poster URL, and a deep link into Jellyseerr.

---

## New Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/search` | Jellyseerr search proxy |
| `GET` | `/api/containers` | All container statuses |
| `POST` | `/actions/restart` | Restart all containers except self |
| `POST` | `/actions/rebuild` | Pull + recreate all containers except self |

Existing `/api/status` and webhook endpoints unchanged.

---

## Docker Changes

**`services/movieseer.yml`**:
- Build context: `../movieseer`
- Container name: `movieseer`
- Mount `/var/run/docker.sock:/var/run/docker.sock`
- Add `JELLYFIN_URL` / `JELLYFIN_API_KEY` env vars (for future use)

**`docker-compose.yml`**:
- Replace `services/pipeline-status.yml` include with `services/movieseer.yml`
- Remove `services/homepage.yml` include

**`movieseer/requirements.txt`**:
- Add `docker` (Python SDK)

---

## Software Stack

### Backend
- **Python 3.11+** — existing language choice, no reason to change
- **FastAPI** — existing framework; handles API routes, webhook receivers, and static file serving
- **Uvicorn** — existing ASGI server
- **httpx** — existing async HTTP client used for all service API calls (Jellyseerr, Radarr, Sonarr, SABnzbd, qBittorrent, Prowlarr)

### New dependencies
- **`docker` (Python SDK)** — for reading container status and issuing restart commands via the Docker socket
- **`jinja2`** — for templating the dashboard HTML. The current approach serves a static `index.html` via `FileResponse`, which works now but won't scale once the UI needs server-rendered state. FastAPI has first-class `Jinja2Templates` support.

### Frontend
- **Vanilla HTML/CSS/JS** — no framework. The mockup demonstrates this is achievable with plain CSS grid and a small amount of JS. Keeps the container lightweight and avoids a build step.

### Infrastructure
- **Docker Compose** — existing orchestration; Movieseer runs as one service among many
- **Docker socket** (`/var/run/docker.sock`) — mounted into the container to enable service health and control features

### Coding Philosophy

- Extensibility is key. Swapping out components should not be laborious; adding new ones should be minimally invasive.
- As much as possible individual components should be as self-contained as is reasonable. Smaller functions are easier to test. A single function, object, or class should have a single clear purpose, although avoid over-abstraction.
- Make type hints clear and explicit.
- All I/O must be async.
- Graceful degradation. Always render something on the dashboard, avoid obscure renderings or error messages. 
- Strive to hardcode absolutely nothing. This may not always be possible, but an environment variable should only need to be changed in one place for this to percolate throughout the stack. All environment variables should be read in a single `config.py` — not scattered across modules as individual `os.getenv` calls. The existing `aggregator.py` does this today and will need refactoring as part of the migration.
- Docstrings are a must, and explicit, clear variable names are desired. Prefer verbose docstrings describing the _why_ of the function, not just the what. NumPy docstring
style is preferred. 
- Loggers will help debug in the future. 
- Tests must be small, focused components. High coverage of business logic (>90%), with tests specific enough to pinpoint failures. Unit tests should out number integration tests.


---

## Migration

- Move `scripts/pipeline-status/` → `movieseer/`
- Rename `services/pipeline-status.yml` → `services/movieseer.yml`
- Remove `homepage` and `pipeline-status` from `docker-compose.yml` includes, add `movieseer`
- Update any `.env` vars that were Homepage-specific
- `${PIPELINE_STATUS_PORT}` becomes the primary dashboard port (consider renaming the var)
