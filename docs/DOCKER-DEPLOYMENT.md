# Phase 4 Docker deployment

Phase 4 adds a container boundary around Hermes while keeping the host
persistent data directory outside the image.

## Security model

The assistant container runs with:

- A multi-stage project-overlay image based on a pinned Hermes release.
- Non-root execution mapped to the host operator UID for private bind mounts.
- Read-only container root filesystem.
- Only `/data` mounted read-write for Hermes state and credentials.
- `/run/personal-assistant-tmp` and `/tmp` as `tmpfs` with `noexec`, `nosuid`,
  and `nodev`.
- All Linux capabilities dropped.
- `no-new-privileges`.
- PID and memory/CPU limits.
- No Docker socket, host home directory, or terminal tool exposure.
- Gmail-only source selection.

The container joins an internal Docker network with no direct outbound route.
It can reach the separate Squid proxy container only. Squid allows only:

```text
gmail.googleapis.com
oauth2.googleapis.com
discord.com, gateway.discord.gg, and cdn.discordapp.com
host.docker.internal:11434  # host Ollama
```

Microsoft Graph is not in the allowlist while Microsoft is disabled. The
Discord adapter uses `DISCORD_PROXY`; Python HTTP clients use the standard
proxy variables.

## Build

Docker must be running. Build the Hermes overlay image:

```bash
cd personal-digital-assistant
./scripts/build-pda-image.sh
```

The default base is pinned for the current Apple Silicon deployment:

```text
nousresearch/hermes-agent:latest@sha256:da20e13cc04fb7ade2a4725255870ebb5f367ec60e89d21707d35bc09a10a934
```

For another architecture, override `HERMES_IMAGE` with the reviewed digest
for that platform. Do not switch back to a floating tag in production.

For a production deployment, replace it with a reviewed immutable digest:

```bash
HERMES_IMAGE='nousresearch/hermes-agent:0.20.6@sha256:REVIEWED_DIGEST' \
  ./scripts/build-pda-image.sh
```

The build context explicitly excludes OAuth material, tokens, credentials,
`.env`, runtime state, tests, documentation, and Python caches.

## Start the egress proxy

```bash
./scripts/start-pda-egress.sh
```

This creates:

```text
personal-assistant-internal   internal/no-direct-egress network
personal-assistant-egress-out proxy outbound network
personal-assistant-egress     allowlisted proxy container
```

The assistant is attached only to `personal-assistant-internal`. The proxy is
the only container attached to both networks. The development default uses
a platform-specific pinned `ubuntu/squid` digest; override `SQUID_IMAGE` only
when changing architecture or after reviewing an image update.

## Start the assistant container

```bash
./scripts/run-pda-container.sh
```

The script requires the existing persistent profile to contain:

```text
<data>/.env
<data>/credentials/gmail.json
```

It creates the Docker-specific read-only profile at:

```text
<data>/docker-config.yaml
```

That profile points Ollama to:

```text
http://host.docker.internal:11434/v1
```

The host Ollama service must be listening on port `11434`.

Inspect logs:

```bash
docker logs -f personal-assistant-hermes
```

When Hermes runs inside Docker, do not use the host-side `hermes cron status`
command as the health check. The gateway's Unix control socket cannot be
placed on a macOS bind mount and is intentionally non-fatal. Use Docker
container state and logs instead:

```bash
docker ps --filter name=personal-assistant-hermes
docker logs --tail 100 personal-assistant-hermes
docker exec personal-assistant-hermes hermes cron list
```

Check the container:

```bash
docker inspect personal-assistant-hermes \
  --format '{{json .HostConfig}}' | python3 -m json.tool
```

The report cron remains Hermes' internal cron. Docker does not create a new
scheduler.

## Stop and rollback

If Phase 5 launchd supervision is installed, stop it first so it does not
immediately restart the containers:

```bash
./scripts/uninstall-launchd.sh
./scripts/stop-pda-container.sh
```

The existing host gateway can then be started again with:

```bash
./scripts/run-hermes-gateway.sh
```

The `/data` bind mount remains untouched when the containers are removed.

## Important limitation

This phase provides the Docker image, hardening flags, persistent mount, and
allowlisted proxy topology. Do not remove the proxy or replace the internal
network with Docker's default bridge network in production; doing so removes
the egress boundary. launchd supervision is Phase 5 and is intentionally not
installed by these scripts.
