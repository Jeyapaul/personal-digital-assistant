# Phase 3 Discord DM setup

Discord is configured as a single-user DM delivery channel. The scheduled
agent cannot choose a recipient, guild, channel, or Discord action.

## Operator steps

1. Open <https://discord.com/developers/applications>.
2. Create a Discord application and add a bot.
3. Reset/copy the bot token. Never paste it into chat or commit it.
4. Enable **Message Content Intent** under the bot's privileged gateway intents.
5. Install the bot in a private server or otherwise make it available to your
   account with the minimum permissions needed for DM use.
6. In Discord, enable **Developer Mode** under User Settings → Advanced.
7. Right-click your own Discord profile and choose **Copy User ID**.

Run the setup script locally. It prompts for the token without echoing it:

```bash
cd personal-digital-assistant
python3 scripts/discord-setup.py \
  --user-id 'YOUR_NUMERIC_DISCORD_USER_ID' \
  --replace-token
```

The script:

- Validates the bot token with Discord.
- Creates/resolves a DM channel for only the supplied user ID.
- Writes the token to the persistent data directory with mode `0600`.
- Writes the profile-scoped Hermes `.env` with the bot token, allowed user,
  and DM channel ID.
- Writes non-secret runtime metadata for the cron installer.

It does not print the bot token.

## Install the Hermes cron job

After Discord setup succeeds:

```bash
./scripts/install-report-cron.sh
```

This is idempotent. It creates or updates one job named
`personal-assistant-daily-mail-report` with:

```text
Schedule: 0 10 * * *
Timezone: Asia/Kolkata
Delivery: discord:<resolved DM channel ID>
Model: the configured LM Studio `PDA_MODEL`; production requires native context >= 64K
Mode: Hermes agent-mode delivery with a fixed pre-run collector and local model summaries
```

The fixed pre-run collector calls the bounded `mail_report` capability exactly
once, summarizes every returned message in batches of five, and renders all
messages in successive report batches of at most 25 messages. Hermes agent mode
is instructed to relay the complete script output verbatim without summarizing,
shortening, or reordering it. The final response is delivered through the
Discord adapter, which automatically sends successive messages under Discord's
2,000-character limit. The next scheduled run marks only the prior
report's messages read after successful delivery is verified; failed delivery
leaves them unread. New-mail mutation recommendations are sent as a separate
approval DM. Reply to that exact approval message with `APPROVE ALL <batch_id>`,
`APPROVE <recommendation_id>`, or `DENY <recommendation_id>`. Every decision is audited. Unmentioned recommendations remain unapproved
until explicitly decided, and approval requests remain open indefinitely.
Mutations are enabled only through the explicit `PDA_MAIL_MUTATION_ENABLED=true`
configuration.
The current 32K model is retained only for bounded validation until a 64K+
candidate is approved.

## Start the gateway

The built-in Hermes cron ticker runs inside the gateway. Start it with:

```bash
./scripts/run-hermes-gateway.sh
```

Do not use launchd yet; launchd belongs to Phase 5. Do not create a second
cron scheduler.

## DM-only controls

The profile applies all of these controls:

- `DISCORD_ALLOWED_USERS=<your user ID>`
- `DISCORD_ALLOW_ALL_USERS=false`
- `discord.ignored_channels: ['*']`
- `discord.auto_thread: false`
- `platform_toolsets.discord: []`
- Cron delivery targets the resolved DM channel directly.

If the bot token is ever exposed or reset, rerun the setup with
`--replace-token`. The script will prompt for the new token and overwrite the
private token file.
