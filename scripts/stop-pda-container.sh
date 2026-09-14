#!/bin/sh
set -eu
CONTAINER=${PDA_CONTAINER:-personal-assistant-hermes}
PROXY=${PDA_EGRESS_CONTAINER:-personal-assistant-egress}
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker rm -f "$PROXY" >/dev/null 2>&1 || true
echo "Stopped personal assistant containers"
