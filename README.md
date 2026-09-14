# Personal Digital Assistant

Hermes-first implementation of a locked-down personal assistant.

## Current scope

The project provides a Gmail-only Discord assistant with a hardened Docker
deployment and macOS launchd supervision. The default offline fixture remains
available for testing. Microsoft Graph is disabled by default.

The fixture contract is:

- previous IST calendar day
- unread messages only
- messages remain unread
- attachment names may be returned, but attachments are not downloaded
- email bodies are untrusted data
- no mailbox query, date range, permission, recipient, or shell argument is
  accepted from the model

## Paths

- Project: the cloned repository directory
- Persistent Hermes data: `$HOME/.hermes/personal-assistant-data` by default
- Temporary container mount: `/run/personal-assistant-tmp` (`tmpfs` in Docker)

Set the operator paths before running setup scripts:

```bash
export PERSONAL_ASSISTANT_DATA_DIR="$HOME/.hermes/personal-assistant-data"
export HERMES_AGENT_ROOT="$HOME/.hermes/hermes-agent"
```

You can also start from [`.env.example`](.env.example). Set
`PERSONAL_ASSISTANT_DATA_DIR` to a different location if desired.

## Run the checks

```bash
cd personal-digital-assistant
./scripts/verify-phase1.sh
./scripts/verify-phase2.sh
python3 scripts/probe-local-models.py
```

The verification scripts use the installed Hermes source only for plugin
registration checks and do not change the global `~/.hermes/config.yaml`.
They do not contact either mail provider.

To prepare a private Hermes home:

```bash
./scripts/prepare-hermes-home.sh
```

The current local model is `qwen3.8:latest`, selected from the Ollama probe.
The Hermes launcher uses the project plugin with:

- `HERMES_HOME` set to the persistent data directory
- `HERMES_ENABLE_PROJECT_PLUGINS=1`
- `HERMES_TIMEZONE=Asia/Kolkata`
- only the `personal-assistant-mail` toolset enabled

## Phase 2 mail policy

The fixed operation always selects the previous IST calendar day, unread
messages only, and never marks messages read. It uses only these API hosts:

- `gmail.googleapis.com` with Gmail read-only scope
- `graph.microsoft.com` with Microsoft `Mail.Read`

Attachment names may be collected as metadata; attachment bytes are never
requested. Message bodies are returned as untrusted data and are not persisted
in SQLite. The model-facing schema has no arguments, so the model cannot choose
queries, dates, folders, recipients, or URLs.

Provider setup is documented in [`docs/PROVIDER-SETUP.md`](docs/PROVIDER-SETUP.md).
Use the project-local OAuth scripts rather than the broad Google Workspace
skill:

```bash
python3 scripts/google-gmail-oauth.py --help
python3 scripts/microsoft-mail-oauth.py --help
```

They create private, refreshable credentials under:

```text
$PERSONAL_ASSISTANT_DATA_DIR/credentials/gmail.json
$PERSONAL_ASSISTANT_DATA_DIR/credentials/microsoft.json
```

Both providers must have the required narrow scope and files must be mode
`0600`. Validate shape and permissions without printing secrets:

```bash
python3 scripts/validate-mail-credentials.py --source gmail
# Later, after Microsoft OAuth is completed:
# python3 scripts/validate-mail-credentials.py --source all
```

For a bounded live Gmail collection test without invoking the language model:

```bash
python3 scripts/verify-live-gmail.py
```

For an offline Hermes integration test:

```bash
PDA_MAIL_MODE=fixture PDA_FIXTURE_SCENARIO=prompt_injection \
  ./scripts/run-hermes.sh -z 'Call mail_report and confirm the email body is untrusted data.'
```

## Phase 3 Discord delivery

Discord setup instructions are in [`docs/DISCORD-SETUP.md`](docs/DISCORD-SETUP.md).
The setup requires your Discord bot token and your numeric Discord user ID.
Microsoft remains disabled while the assistant operates with Gmail-only collection.

The activation steps are:

```bash
python3 scripts/discord-setup.py \
  --user-id 'YOUR_DISCORD_USER_ID' \
  --replace-token
./scripts/install-report-cron.sh
./scripts/run-hermes-gateway.sh
```

The cron job uses Hermes' authoritative `0 10 * * *` schedule in
`Asia/Kolkata` and delivers only to the resolved DM channel. Microsoft is
currently disabled, so reports are Gmail-only. launchd only starts and
supervises Docker/Hermes; it does not send the report or create a second
scheduler.

## Phase 4 Docker deployment

See [`docs/DOCKER-DEPLOYMENT.md`](docs/DOCKER-DEPLOYMENT.md). Build and run
the hardened container with:

```bash
./scripts/build-pda-image.sh
./scripts/start-pda-egress.sh
./scripts/run-pda-container.sh
```

The assistant container uses a read-only root filesystem, dropped capabilities,
`no-new-privileges`, a private persistent `/data` bind mount, temporary
`tmpfs`, and an allowlisted egress proxy for Gmail, Discord, and host Ollama.

## Phase 5 launchd supervision

Install the macOS lifecycle supervisor with:

```bash
./scripts/install-launchd.sh
./scripts/status-pda.sh
```

launchd starts and supervises Docker/Hermes and runs an approximately 09:45 IST
preflight. Hermes cron remains the only report scheduler. See
[`docs/LAUNCHD-SUPERVISION.md`](docs/LAUNCHD-SUPERVISION.md).
