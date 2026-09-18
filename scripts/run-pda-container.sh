#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DATA_DIR=${PERSONAL_ASSISTANT_DATA_DIR:-$HOME/.hermes/personal-assistant-data}
IMAGE=${PDA_IMAGE:-personal-assistant-hermes:0.20.6}
CONTAINER=${PDA_CONTAINER:-personal-assistant-hermes}
INTERNAL_NET=${PDA_INTERNAL_NETWORK:-personal-assistant-internal}
PROXY=${PDA_EGRESS_CONTAINER:-personal-assistant-egress}
MAIL_SOURCES=${PDA_MAIL_SOURCES:-gmail}
NEW_MAIL_REVIEW=${PDA_NEW_MAIL_REVIEW:-true}
MODEL=${PDA_MODEL:-qwen3.8-pda:64k}
case "$MODEL" in
  (*[!A-Za-z0-9._:-]*) echo "Invalid PDA_MODEL" >&2; exit 2 ;;
esac
HOST_GATEWAY=${PDA_HOST_GATEWAY:-$(docker run --rm --add-host host.docker.internal:host-gateway alpine:3.22 getent ahostsv4 host.docker.internal | awk 'NR==1 {print $1}')}
if [ -z "$HOST_GATEWAY" ]; then
  echo "Unable to resolve the Docker host gateway IPv4 address" >&2
  exit 2
fi

"$ROOT/scripts/prepare-hermes-home.sh" >/dev/null
if [ ! -f "$DATA_DIR/.env" ] || [ ! -f "$DATA_DIR/credentials/gmail.json" ]; then
  echo "Discord/Gmail credentials are missing from $DATA_DIR" >&2
  exit 2
fi
DOCKER_CONFIG="$DATA_DIR/docker-config.yaml"
if [ ! -f "$DOCKER_CONFIG" ]; then
  cp "$ROOT/config/hermes-docker.yaml" "$DOCKER_CONFIG"
  chmod 600 "$DOCKER_CONFIG"
fi
# Keep the persistent Docker profile aligned with the selected local model.
# The model name is restricted above and the edit uses only the standard
# library, so this does not require PyYAML on the host.
python3 - "$DOCKER_CONFIG" "$MODEL" <<'PY'
import re
import sys
from pathlib import Path
path, model = Path(sys.argv[1]), sys.argv[2]
text = path.read_text(encoding="utf-8")
updated, count = re.subn(r"(?m)^(\s+default:\s+).+$", rf"\g<1>{model}", text, count=1)
if count != 1:
    raise SystemExit("Docker Hermes profile has no model.default entry")
path.write_text(updated, encoding="utf-8")
path.chmod(0o600)
PY
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Missing image $IMAGE; run scripts/build-pda-image.sh first" >&2
  exit 2
fi
if ! docker container inspect "$PROXY" >/dev/null 2>&1; then
  echo "Missing egress proxy $PROXY; run scripts/start-pda-egress.sh first" >&2
  exit 2
fi

# The image WORKDIR is /opt/personal-assistant. Clear the host-only workdir so
# both host and container gateways use their own current working directory.
PDA_CRON_WORKDIR= "$ROOT/scripts/install-report-cron.sh" >/dev/null

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
HOST_UID=$(id -u)
HOST_GID=$(id -g)

docker run -d \
  --name "$CONTAINER" \
  --network "$INTERNAL_NET" \
  --add-host "host.docker.internal:$HOST_GATEWAY" \
  --restart unless-stopped \
  --init \
  --read-only \
  --user "$HOST_UID:$HOST_GID" \
  --cap-drop=ALL \
  --security-opt no-new-privileges:true \
  --pids-limit 256 \
  --memory 1536m \
  --cpus 2 \
  --tmpfs "/run/personal-assistant-tmp:rw,noexec,nosuid,nodev,size=64m,uid=$HOST_UID,gid=$HOST_GID,mode=700" \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=32m \
  --mount "type=bind,src=$DATA_DIR,dst=/data" \
  --mount "type=bind,src=$DOCKER_CONFIG,dst=/data/config.yaml,ro" \
  -e HTTP_PROXY=http://egress-proxy:3128 \
  -e HTTPS_PROXY=http://egress-proxy:3128 \
  -e ALL_PROXY=http://egress-proxy:3128 \
  -e NO_PROXY= \
  -e DISCORD_PROXY=http://egress-proxy:3128 \
  -e PERSONAL_ASSISTANT_DATA_DIR=/data \
  -e PDA_MAIL_SOURCES="$MAIL_SOURCES" \
  -e PDA_NEW_MAIL_REVIEW="$NEW_MAIL_REVIEW" \
  "$IMAGE"

echo "Started $CONTAINER"
