#!/usr/bin/env zsh
set -e

SCRIPT_DIR="${0:A:h}"
PATH_TO_ROOT="$(dirname "$SCRIPT_DIR")"
if [[ "$(basename "$PATH_TO_ROOT")" != "movieseer" ]]; then
  echo "Error: Script is expected to be one folder down from the project root. Current path: $SCRIPT_DIR"
  exit 1
fi

NUM_ARGS=$#
REBUILD=false
ISOLATE=false

# Load .env to get DATA_PATH and port variables
source "$PATH_TO_ROOT/.env"

if [[ $NUM_ARGS -gt 0 ]]; then
  for var in "$@"; do
    case "$var" in
      --down*)
        cd "$PATH_TO_ROOT"
        docker compose down
        exit 0
        ;;
      --rebuild)
        REBUILD=true
        ;;
      --murder)
        cd "$PATH_TO_ROOT"
        docker compose down
        docker desktop stop
        diskutil eject "$(dirname "$DATA_PATH")"
        exit 0
        ;;
      --isolate)
        ISOLATE=true
        ;;
      *)
        echo "Unknown argument: $var"
        echo "Usage: $0 [--down] [--rebuild] [--murder]"
        exit 1
        ;;
    esac
  done
fi


# 0. Check that the media volume is mounted

if [[ ! -d "$DATA_PATH" ]]; then
  osascript -e "display alert \"Volume not mounted\" message \"$DATA_PATH does not exist. Please mount the drive before starting Movieseer.\" as critical"
  exit 1
fi
echo "Volume $DATA_PATH is mounted."

# 1. Ensure Tailscale is running
if /usr/local/bin/tailscale status &>/dev/null; then
  echo "Tailscale is already connected."
else
  echo "Starting Tailscale..."
  open -g -a Tailscale
fi

# 2. Launch Docker Desktop if not already running
if ! docker info &>/dev/null; then
  echo "Starting Docker Desktop..."
  open -g -a Docker
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
start_containers() {
  echo "Starting containers..."
  cd "$PATH_TO_ROOT"
  docker network create movieseer 2>/dev/null || true
  if [[ "$REBUILD" == true ]]; then
    docker compose build movieseer
  fi
  if [[ "$ISOLATE" == true ]]; then
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
  else
    docker compose up -d
  fi
}

start_containers

# 4. Wait for each service to be reachable
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

echo ""
echo "Waiting for services to be ready..."

wait_for "Jellyfin"       "http://localhost:${JELLYFIN_PORT}/health"
wait_for "Plex"           "http://localhost:${PLEX_PORT}/identity"
wait_for "Sonarr"         "http://localhost:${SONARR_PORT}/ping"
wait_for "Radarr"         "http://localhost:${RADARR_PORT}/ping"
wait_for "Prowlarr"       "http://localhost:${PROWLARR_PORT}/ping"
wait_for "SABnzbd"        "http://localhost:${SABNZBD_PORT}/"
wait_for "Jellyseerr"     "http://localhost:${JELLYSEERR_PORT}/"
wait_for "Flaresolverr"   "http://localhost:${FLARESOLVERR_PORT}/"
wait_for "Movieseer"      "http://localhost:${MOVIESEER_PORT}/"

# 5. Open Movieseer
echo ""
echo "All services ready. Opening Movieseer..."
open "http://localhost:${MOVIESEER_PORT}"
