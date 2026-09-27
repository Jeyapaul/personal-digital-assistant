# Personal Digital Assistant implementation plan

## Architecture decision

Hermes remains the scheduler, agent-mode Discord relay, local-model runner, and
fixed capability host. The scheduled agent receives a complete pre-run report
and is instructed to relay it verbatim; the Discord adapter handles successive
messages when needed. The current deployment uses local LM Studio with Qwen3
30B-A3B; an OpenRouter migration is evaluated but not selected in
[`docs/OPENROUTER-MODEL-EVALUATION.md`](OPENROUTER-MODEL-EVALUATION.md).
The fixed collector exposes only the operator-authored `mail_report` boundary;
its scheduled profile exposes no callable mail tool. It does not expose
terminal, skills, Himalaya, the general Google Workspace skill, shell execution,
or provider mutation operations.

The Google Workspace Hermes skill is useful as an OAuth reference, but its
installed setup currently requests Gmail send/modify plus Calendar, Drive,
Sheets, Docs, and Contacts scopes. Its documentation mentions `--services`,
but the installed setup script does not implement that argument. It is
therefore not used directly.

Himalaya is retained only as an optional manual IMAP diagnostic. Its normal
Gmail App Password setup is not read-only, it supports SMTP and mailbox
mutation, and its unread-preservation behavior must not be assumed for the
scheduled job.

## Phases

1. **Feasibility:** local LM Studio model, project plugin, fixed stub, and
   prompt-injection tests. Complete.
2. **Mail collection:** dedicated narrow reporting and management OAuth,
   fixed previous-IST-day collection, incremental new-mail cursor review,
   refresh-token support, complete provider pagination, 25-message report
   batching, SQLite run state, post-delivery read marking, and offline contract
   tests. OAuth bootstrap implementation is included; live consent is performed
   by the operator. Organizer mutations remain disabled.
3. **Delivery:** restricted Discord DM delivery and Hermes cron provisioning.
   Gmail and Microsoft are supported when their narrow OAuth credentials are
   available.
4. **Deployment:** hardened multi-stage Docker image, persistent `/data`,
   temporary `/run/personal-assistant-tmp`, and network egress policy.
   Complete for the current Apple Silicon deployment. The image and Squid
   proxy use reviewed platform-specific digests; re-review them when updating.
5. **Lifecycle:** launchd startup, health checks, restart handling, and
   preflight without a second scheduler. Complete for the current macOS user
   session; see `docs/LAUNCHD-SUPERVISION.md`. Local model context sizing is
   part of the deployment profile.

## Operator-owned prerequisites

- A Google Cloud desktop OAuth client with Gmail API enabled and the account
  authorized as a test user or the app published/allowlisted.
- A Microsoft Entra app registration with delegated `Mail.Read`, public-client
  device-code flow enabled, and user/admin consent when Microsoft is enabled.
- A Discord bot token and the operator's numeric Discord user ID before Phase
  3 can be activated.
- The persistent data directory must remain private. OAuth files are created
  with mode `0600` by the setup scripts.
- The operator must complete browser consent; the assistant never receives a
  Google password, Microsoft password, or raw client secret in a prompt.
