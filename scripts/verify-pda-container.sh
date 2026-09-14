#!/bin/sh
set -eu

CONTAINER=${PDA_CONTAINER:-personal-assistant-hermes}
PROXY=${PDA_EGRESS_CONTAINER:-personal-assistant-egress}
IMAGE=${PDA_IMAGE:-personal-assistant-hermes:0.20.6}

[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = true ] || {
  echo "assistant container is not running" >&2
  exit 1
}
[ "$(docker inspect -f '{{.State.Running}}' "$PROXY" 2>/dev/null)" = true ] || {
  echo "egress proxy is not running" >&2
  exit 1
}

readonly=$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$CONTAINER")
network=$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$CONTAINER")
security=$(docker inspect -f '{{join .HostConfig.SecurityOpt " "}}' "$CONTAINER")
caps=$(docker inspect -f '{{join .HostConfig.CapDrop " "}}' "$CONTAINER")
user=$(docker inspect -f '{{.Config.User}}' "$CONTAINER")

[ "$readonly" = true ] || { echo "root filesystem is writable" >&2; exit 1; }
[ "$network" = "personal-assistant-internal" ] || { echo "unexpected network: $network" >&2; exit 1; }
echo "$security" | grep -q 'no-new-privileges:true' || { echo "no-new-privileges missing" >&2; exit 1; }
echo "$caps" | grep -qw ALL || { echo "all capabilities were not dropped" >&2; exit 1; }
[ -n "$user" ] || { echo "container has no explicit user" >&2; exit 1; }

# The proxy must be the only bridge from the internal network to outbound.
internal=$(docker network inspect personal-assistant-internal -f '{{len .Containers}}')
outbound=$(docker network inspect personal-assistant-egress-out -f '{{len .Containers}}')
[ "$internal" -ge 2 ] || { echo "internal network does not contain assistant and proxy" >&2; exit 1; }
[ "$outbound" = 1 ] || { echo "unexpected outbound-network members: $outbound" >&2; exit 1; }

# Allowed hosts return an HTTP response; an unrelated host is denied.
allowed=$(docker run --rm --network personal-assistant-internal --entrypoint /usr/bin/curl "$IMAGE" \
  --max-time 15 --silent --output /dev/null --write-out '%{http_code}' \
  --proxy http://egress-proxy:3128 https://gmail.googleapis.com/gmail/v1/users/me/profile)
[ "$allowed" != 000 ] || { echo "allowlisted Gmail endpoint unreachable" >&2; exit 1; }
if docker run --rm --network personal-assistant-internal --entrypoint /usr/bin/curl "$IMAGE" \
  --max-time 15 --silent --output /dev/null \
  --proxy http://egress-proxy:3128 https://example.com >/dev/null 2>&1; then
  echo "unrelated egress was not denied" >&2
  exit 1
fi

printf '%s\n' "PASS: container hardening, network topology, and allowlist checks"
