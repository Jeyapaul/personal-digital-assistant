#!/bin/sh
set -eu

IMAGE=${PDA_EGRESS_IMAGE:-personal-assistant-egress:0.1}
SQUID_IMAGE=${SQUID_IMAGE:-ubuntu/squid:latest@sha256:6a097f68bae708cedbabd6188d68c7e2e7a38cedd05a176e1cc0ba29e3bbe029}
PROXY=${PDA_EGRESS_CONTAINER:-personal-assistant-egress}
INTERNAL_NET=${PDA_INTERNAL_NETWORK:-personal-assistant-internal}
OUT_NET=${PDA_EGRESS_NETWORK:-personal-assistant-egress-out}
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
HOST_GATEWAY=${PDA_HOST_GATEWAY:-$(docker run --rm --add-host host.docker.internal:host-gateway alpine:3.22 getent ahostsv4 host.docker.internal | awk 'NR==1 {print $1}')}
if [ -z "$HOST_GATEWAY" ]; then
  echo "Unable to resolve the Docker host gateway IPv4 address" >&2
  exit 2
fi

for network in "$INTERNAL_NET" "$OUT_NET"; do
  if ! docker network inspect "$network" >/dev/null 2>&1; then
    if [ "$network" = "$INTERNAL_NET" ]; then
      docker network create --internal "$network" >/dev/null
    else
      docker network create "$network" >/dev/null
    fi
  fi
done

if [ "${PDA_SKIP_BUILD:-0}" = 1 ]; then
  docker image inspect "$IMAGE" >/dev/null 2>&1 || {
    echo "Missing egress image $IMAGE; build it before starting the supervisor" >&2
    exit 2
  }
else
  docker build --pull --build-arg "SQUID_IMAGE=$SQUID_IMAGE" -t "$IMAGE" "$ROOT/docker/egress"
fi
if [ "${PDA_RECREATE:-0}" = 1 ]; then
  docker rm -f "$PROXY" >/dev/null 2>&1 || true
fi
if docker container inspect "$PROXY" >/dev/null 2>&1; then
  docker start "$PROXY" >/dev/null 2>&1 || true
  echo "$PROXY already exists"
  exit 0
fi

# Attach the proxy to the internal network and the ordinary outbound network.
# The assistant joins only the internal network, so it cannot bypass Squid.
docker create \
  --name "$PROXY" \
  --network "$INTERNAL_NET" \
  --network-alias egress-proxy \
  --add-host "host.docker.internal:$HOST_GATEWAY" \
  --restart unless-stopped \
  --read-only \
  --cap-drop=ALL \
  --cap-add=SETUID \
  --cap-add=SETGID \
  --security-opt no-new-privileges:true \
  --pids-limit 128 \
  --memory 256m \
  --tmpfs /var/cache/squid:rw,noexec,nosuid,nodev,size=32m \
  --tmpfs /var/log/squid:rw,noexec,nosuid,nodev,size=16m \
  "$IMAGE" squid -N -f /etc/squid/squid.conf >/dev/null
docker network connect "$OUT_NET" "$PROXY"
docker start "$PROXY" >/dev/null
echo "Started $PROXY with allowlisted egress"
