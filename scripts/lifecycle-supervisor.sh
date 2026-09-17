#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DATA_DIR=${PERSONAL_ASSISTANT_DATA_DIR:-$HOME/.hermes/personal-assistant-data}
CONTAINER=${PDA_CONTAINER:-personal-assistant-hermes}
PROXY=${PDA_EGRESS_CONTAINER:-personal-assistant-egress}
LOG_DIR="$DATA_DIR/lifecycle"
LOCK_DIR="$LOG_DIR/supervisor.lock"
INTERVAL=${PDA_SUPERVISOR_INTERVAL:-30}

mkdir -p "$LOG_DIR"
log() {
  printf '%s %s\n' "$(TZ=Asia/Kolkata date '+%Y-%m-%dT%H:%M:%S%z')" "$*"
}

# launchd should never run two copies of this supervisor. A hard kill or
# machine restart can leave the old lock behind, so reclaim it when its owner
# is no longer alive.
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  owner=""
  [ -r "$LOCK_DIR/pid" ] && owner=$(cat "$LOCK_DIR/pid" 2>/dev/null || true)
  if [ -n "$owner" ] && kill -0 "$owner" 2>/dev/null; then
    log "another lifecycle supervisor is already running (pid=$owner)"
    exit 0
  fi
  rmdir "$LOCK_DIR" 2>/dev/null || {
    log "unable to reclaim stale supervisor lock"
    exit 1
  }
  mkdir "$LOCK_DIR"
fi
printf '%s\n' "$$" > "$LOCK_DIR/pid"
cleanup() {
  rm -f "$LOCK_DIR/pid" 2>/dev/null || true
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

open_docker() {
  open -gj -a Docker >/dev/null 2>&1 || true
}

docker_ready() {
  docker info >/dev/null 2>&1
}

container_running() {
  [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" = true ]
}

credential_health() {
  output=$(PERSONAL_ASSISTANT_DATA_DIR="$DATA_DIR" \
    PDA_MAIL_SOURCES="${PDA_MAIL_SOURCES:-gmail}" \
    python3 "$ROOT/scripts/credential-health.py" 2>&1 || true)
  if [ -n "$output" ]; then
    log "credential health: $output"
  fi
}

ensure_runtime() {
  if ! docker_ready; then
    log "Docker is unavailable; requesting Docker Desktop startup"
    open_docker
    return 1
  fi
  if ! container_running "$PROXY"; then
    log "starting egress proxy"
    PDA_SKIP_BUILD=1 "$ROOT/scripts/start-pda-egress.sh"
  fi
  if ! container_running "$CONTAINER"; then
    log "starting Hermes assistant container"
    "$ROOT/scripts/run-pda-container.sh"
  fi
  return 0
}

preflight() {
  if ! ensure_runtime; then
    log "preflight deferred because Docker is unavailable"
    return 1
  fi
  log "running daily preflight"
  PERSONAL_ASSISTANT_DATA_DIR="$DATA_DIR" \
    python3 "$ROOT/scripts/validate-mail-credentials.py" --source gmail >/dev/null
  PDA_CONTAINER="$CONTAINER" PDA_EGRESS_CONTAINER="$PROXY" \
    "$ROOT/scripts/verify-pda-container.sh" >/dev/null
  docker exec "$CONTAINER" hermes cron list >/dev/null
  date_key=$(TZ=Asia/Kolkata date '+%Y-%m-%d')
  : > "$LOG_DIR/preflight-$date_key.ok"
  log "daily preflight passed for $date_key"
}

run_once() {
  credential_health
  ensure_runtime || return 0
  now_minutes=$(TZ=Asia/Kolkata date '+%H%M')
  date_key=$(TZ=Asia/Kolkata date '+%Y-%m-%d')
  marker="$LOG_DIR/preflight-$date_key.ok"
  # This is only a health check. It never calls cron tick/run and never sends
  # the report; Hermes cron remains the sole report scheduler.
  if [ "$now_minutes" -ge 0945 ] && [ ! -e "$marker" ]; then
    preflight || log "daily preflight failed; will retry"
  fi
}

if [ "${PDA_SUPERVISOR_ONESHOT:-0}" = 1 ]; then
  run_once
  exit 0
fi

log "lifecycle supervisor started; interval=${INTERVAL}s"
while :; do
  run_once || true
  sleep "$INTERVAL"
done
