#!/usr/bin/env zsh
set -e

SCRIPT_DIR="${0:A:h}"
TEST_MODE=false

for arg in "$@"; do
  case $arg in
    --test) TEST_MODE=true ;;
  esac
done

# Load .env to get DATA_PATH and port variables
set -a
if $TEST_MODE; then
  source "$SCRIPT_DIR/.env.test"
else
  source "$SCRIPT_DIR/.env"
fi
set +a

# 0. Check that the media volume is mounted
if $TEST_MODE; then
  echo "Test mode: skipping volume check (DATA_PATH=$DATA_PATH)"
else
  if [[ ! -d "$DATA_PATH" ]]; then
    osascript -e "display alert \"Volume not mounted\" message \"$DATA_PATH does not exist. Please mount the drive before starting Movieseer.\" as critical"
    exit 1
  fi
  echo "Volume $DATA_PATH is mounted."
fi

# 1. Ensure Tailscale is running
if /usr/local/bin/tailscale status &>/dev/null 2>&1; then
  echo "Tailscale is already connected."
else
  echo "Starting Tailscale..."
  open -gj -a Tailscale
fi

# 2. Launch Docker Desktop if not already running
if ! docker info &>/dev/null 2>&1; then
  echo "Starting Docker Desktop..."
  open -gj -a Docker
  echo -n "Waiting for Docker to be ready"
  while ! docker info &>/dev/null 2>&1; do
    echo -n "."
    sleep 2
  done
  echo " ready."
else
  echo "Docker is already running."
fi

# 3. Spin up containers
echo "Starting containers..."
cd "$SCRIPT_DIR"
docker network create movieseer 2>/dev/null || true
if $TEST_MODE; then
  docker compose --env-file "$SCRIPT_DIR/.env.test" up -d
else
  docker compose up -d
fi

if $TEST_MODE; then
  echo "\nTest mode: skipping service health checks."
  echo "Services starting — check 'docker compose ps' to verify."
  exit 0
fi

# 5. Wait for each service to be reachable
# Polls URL every 2s, gives up after max_attempts (default 30 = 60s timeout)
wait_for() {
  local name=$1
  local url=$2
  local max=${3:-30}
  local i=0
  printf "  %-20s" "$name"
  while ! curl -sf -o /dev/null "$url" 2>/dev/null; do
    i=$((i + 1))
    if [[ $i -ge $max ]]; then
      echo "timed out"
      return 1
    fi
    printf "."
    sleep 2
  done
  echo " ready"
}

echo "\nWaiting for services to be ready..."

# Jellyfin runs in Docker, exposes /health
wait_for "Jellyfin"       "http://localhost:${JELLYFIN_PORT}/health"
# *arr services expose /ping without requiring auth
wait_for "Sonarr"         "http://localhost:${SONARR_PORT}/ping"
wait_for "Radarr"         "http://localhost:${RADARR_PORT}/ping"
wait_for "Prowlarr"       "http://localhost:${PROWLARR_PORT}/ping"
# qBittorrent's port is exposed via Gluetun
wait_for "qBittorrent"    "http://localhost:${QBITTORRENT_PORT}/"
wait_for "SABnzbd"        "http://localhost:${SABNZBD_PORT}/"
wait_for "Jellyseerr"     "http://localhost:${JELLYSEERR_PORT}/"
wait_for "Flaresolverr"   "http://localhost:${FLARESOLVERR_PORT}/"
wait_for "Homepage"       "http://localhost:${HOMEPAGE_PORT}/"

# 6. Open Homepage
echo "\nAll services ready. Opening Homepage..."
open "http://localhost:${HOMEPAGE_PORT}"
