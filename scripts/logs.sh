#!/bin/bash

RADARR_LOG="services/config/radarr/logs/radarr.debug.txt"
SONARR_LOG="services/config/sonarr/logs/sonarr.debug.txt"
RADARR_OLD="services/config/radarr/logs/radarr.debug.1.txt"
SONARR_OLD="services/config/sonarr/logs/sonarr.debug.1.txt"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GREY='\033[0;90m'
BOLD='\033[1m'
NC='\033[0m'

format_line() {
  local service="$1"
  local line="$2"

  [[ -z "$line" ]] && return
  # Skip stack trace continuation lines
  [[ "$line" == "   at "* ]] && return

  local timestamp level component message
  timestamp=$(echo "$line" | cut -d'|' -f1)
  level=$(echo "$line"     | cut -d'|' -f2)
  component=$(echo "$line" | cut -d'|' -f3)
  message=$(echo "$line"   | cut -d'|' -f4-)

  case "$component" in
    ProcessDownloadDecisions|TrackedDownloadService|\
    DownloadedMovieImportService|DownloadedEpisodesImportService|\
    ImportApprovedMovies|ImportApprovedEpisodes|\
    RssSyncService|Newznab|CompletedDownloadService)
      ;;
    *) return ;;
  esac

  [[ "$level" == "Debug" ]] && return
  echo "$message" | grep -qE "^Processing [0-9]+|^Starting RSS|Removing failed|RSS Sync Completed. Reports found.*grabbed: 0" && return

  if echo "$message" | grep -qi "Couldn't add\|failed\|error\|unable"; then
    printf "${GREY}%s${NC} ${RED}[FAIL]${NC}   ${GREY}[%s]${NC} %s\n" "$timestamp" "$service" "$message"
  elif echo "$message" | grep -qi "API Request Limit\|Disabled for"; then
    printf "${GREY}%s${NC} ${YELLOW}[LIMIT]${NC}  ${GREY}[%s]${NC} %s\n" "$timestamp" "$service" "$message"
  elif echo "$message" | grep -qi "grabbed\|Reports grabbed: [^0]"; then
    printf "${GREY}%s${NC} ${CYAN}[GRAB]${NC}   ${GREY}[%s]${NC} %s\n" "$timestamp" "$service" "$message"
  elif echo "$message" | grep -qi "Import\|imported"; then
    printf "${GREY}%s${NC} ${GREEN}[IMPORT]${NC} ${GREY}[%s]${NC} %s\n" "$timestamp" "$service" "$message"
  elif [[ "$level" == "Warn" ]]; then
    printf "${GREY}%s${NC} ${YELLOW}[WARN]${NC}   ${GREY}[%s]${NC} %s\n" "$timestamp" "$service" "$message"
  else
    printf "${GREY}%s${NC} [INFO]   ${GREY}[%s]${NC} %s\n" "$timestamp" "$service" "$message"
  fi
}

# Show recent history from log files
show_history() {
  printf "${BOLD}--- Recent activity ---${NC}\n"
  local found=0
  for f in "$RADARR_OLD" "$RADARR_LOG"; do
    [[ -f "$f" ]] || continue
    while IFS= read -r line; do
      result=$(format_line "radarr" "$line")
      [[ -n "$result" ]] && { echo "$result"; found=1; }
    done < "$f"
  done
  for f in "$SONARR_OLD" "$SONARR_LOG"; do
    [[ -f "$f" ]] || continue
    while IFS= read -r line; do
      result=$(format_line "sonarr" "$line")
      [[ -n "$result" ]] && { echo "$result"; found=1; }
    done < "$f"
  done
  [[ $found -eq 0 ]] && echo "(no significant events in recent logs)"
  printf "${BOLD}--- Live feed (Ctrl+C to stop) ---${NC}\n\n"
}

show_history

{
  tail -f "$RADARR_LOG" | sed -u 's/^/RADARR|/' &
  tail -f "$SONARR_LOG" | sed -u 's/^/SONARR|/' &
  wait
} | while IFS= read -r prefixed; do
  service="${prefixed%%|*}"
  line="${prefixed#*|}"
  format_line "$service" "$line"
done
