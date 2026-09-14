#!/bin/sh
set -eu
CONTAINER=${PDA_CONTAINER:-personal-assistant-hermes}
PROXY=${PDA_EGRESS_CONTAINER:-personal-assistant-egress}
LABEL=com.personal-assistant.hermes
printf 'launchd: '
launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 && echo running || echo not-loaded
printf 'proxy: '
docker inspect -f '{{.State.Status}}' "$PROXY" 2>/dev/null || echo missing
printf 'assistant: '
docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo missing
printf 'cron: '
docker exec "$CONTAINER" hermes cron list 2>/dev/null | grep -E 'Next run:|Last run:' | tr '\n' ' ' || echo unavailable
printf '\n'
