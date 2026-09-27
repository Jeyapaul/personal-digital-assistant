#!/bin/sh
set -eu

IMAGE=${PDA_EGRESS_IMAGE:-personal-assistant-egress:0.1}
SQUID_IMAGE=${SQUID_IMAGE:-ubuntu/squid:latest@sha256:6a097f68bae708cedbabd6188d68c7e2e7a38cedd05a176e1cc0ba29e3bbe029}
PROXY=${PDA_EGRESS_CONTAINER:-personal-assistant-egress}
INTERNAL_NET=${PDA_INTERNAL_NETWORK:-personal-assistant-internal}
OUT_NET=${PDA_EGRESS_NETWORK:-personal-assistant-egress-out}
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DATA_DIR=${PERSONAL_ASSISTANT_DATA_DIR:-$HOME/.hermes/personal-assistant-data}
UNSUBSCRIBE_HOSTS_FILE=${PDA_UNSUBSCRIBE_HOSTS_FILE:-$DATA_DIR/config/unsubscribe-hosts.txt}
GENERATED_SQUID_CONFIG=${PDA_GENERATED_SQUID_CONFIG:-$DATA_DIR/config/egress-squid.conf}
UNSUBSCRIBE_ALLOWED_HOSTS=${PDA_UNSUBSCRIBE_ALLOWED_HOSTS:-}
python3 - "$ROOT/docker/egress/squid.conf" "$UNSUBSCRIBE_HOSTS_FILE" "$GENERATED_SQUID_CONFIG" "$UNSUBSCRIBE_ALLOWED_HOSTS" <<'PY'
import re, sys
from pathlib import Path
source = Path(sys.argv[1])
host_file = Path(sys.argv[2])
destination = Path(sys.argv[3])
hosts = []
raw_hosts = (host_file.read_text(encoding="utf-8").splitlines() if host_file.exists() else [])
raw_hosts += sys.argv[4].split(",")
for raw in raw_hosts:
    host = raw.strip().lower().lstrip(".")
    if not host:
        continue
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host):
        raise SystemExit(f"invalid unsubscribe host: {host}")
    hosts.append(host)
text = source.read_text(encoding="utf-8")
if hosts:
    marker = "acl allowed_destinations dstdomain"
    text = text.replace(marker, "acl unsubscribe_destinations dstdomain " + " ".join(sorted(set(hosts))) + "\n" + marker, 1)
    text = text.replace("http_access allow localnet allowed_destinations", "http_access allow localnet allowed_destinations\nhttp_access allow localnet unsubscribe_destinations", 1)
destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
destination.write_text(text, encoding="utf-8")
destination.chmod(0o600)
PY
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
  --mount "type=bind,src=$GENERATED_SQUID_CONFIG,dst=/etc/squid/squid.conf,ro" \
  "$IMAGE" squid -N -f /etc/squid/squid.conf >/dev/null
docker network connect "$OUT_NET" "$PROXY"
docker start "$PROXY" >/dev/null
echo "Started $PROXY with allowlisted egress"
