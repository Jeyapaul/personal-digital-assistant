# Phase 5 launchd supervision

launchd supervises Docker and the Hermes assistant container. It does **not**
run mail reports, tick Hermes cron, or create a second scheduler.

## Installed service

```text
Label: com.personal-assistant.hermes
Plist: ~/Library/LaunchAgents/com.personal-assistant.hermes.plist
```

The service is configured with:

- `RunAtLoad`
- `KeepAlive`
- 30-second restart throttling
- Background process priority
- Persistent lifecycle logs under the Hermes data directory

Install or refresh it with:

```bash
cd personal-digital-assistant
./scripts/install-launchd.sh
```

Check status:

```bash
./scripts/status-pda.sh
launchctl print gui/$(id -u)/com.personal-assistant.hermes
```

Uninstall the supervisor without removing containers or data:

```bash
./scripts/uninstall-launchd.sh
```

## Supervisor behavior

`lifecycle-supervisor.sh` runs in the foreground under launchd and checks every
30 seconds:

1. Docker Desktop is available.
2. The allowlisted egress proxy is running.
3. The hardened Hermes container is running.
4. At or after 09:45 IST, the daily preflight has passed.

If Docker is unavailable, it requests Docker Desktop startup with `open` and
retries. If a managed container has stopped, it starts it again. It never
runs `hermes cron tick`, `hermes cron run`, or a report command.

## 09:45 IST preflight

The preflight runs at the first supervisor check at or after 09:45 IST and is
recorded once per IST date at:

```text
$PERSONAL_ASSISTANT_DATA_DIR/lifecycle/preflight-YYYY-MM-DD.ok
```

It checks:

- Gmail credential shape, exact read-only scope, refresh token, and mode `0600`.
- Container hardening and internal-network topology.
- Gmail allowlisted connectivity through Squid.
- The container's Hermes cron job and next scheduled run.

The preflight does not collect mail, mark messages read, call the model, or
send a Discord report.

## Sleep behavior

macOS launchd and Docker cannot guarantee an exact 10:00 execution if the Mac
is asleep. After wake, launchd restarts/retains the supervisor and the Hermes
container resumes. The preflight runs at the first check after 09:45 if it has
not already run. Hermes remains the authoritative scheduler for the report.

## Health checks

Because Unix control sockets cannot reliably be created on a macOS bind mount,
`hermes cron status` from the host is not the Docker health check. Use:

```bash
./scripts/status-pda.sh
./scripts/verify-pda-container.sh
```

The non-fatal control-socket warning is expected in this bind-mounted macOS
layout. Container state, logs, the internal cron listing, and the preflight
marker are authoritative.
