# OAuth production readiness: durable Google and Microsoft mail credentials

This runbook distinguishes durable provider consent from refresh-token
maintenance. Neither provider offers a permanent refresh token: a user, provider,
security policy, or administrator can revoke access. The goal is to remove
avoidable expiry and detect/recover from unavoidable revocation promptly.

## Current implementation and remaining gaps

### Already implemented

- Google OAuth requests offline access (`access_type=offline`) and explicitly
  requests consent when minting a credential. Report and management scopes are
  separate.
- Microsoft uses device-code authorization with `offline_access`; the Hotmail
  profile uses the `consumers` tenant. Report and management scopes are separate.
- Runtime refresh exchanges store a returned rotated refresh token, updated
  access token, and expiry back to the credential file with mode `0600`.
- `scripts/credential-health.py` attempts a forced refresh hourly for enabled
  **report** credentials, retries failures every five minutes, alerts the
  configured Discord DM, and reports recovery. The launchd supervisor invokes
  it every 30 seconds; this does not imply a provider refresh every 30 seconds.
- OAuth files live in the persistent data directory and encrypted authenticated
  backups are available.

### Production blockers / hardening still required

1. **Google Cloud publishing status is not confirmed.** If the OAuth app is
   External and remains in Testing, Google refresh tokens for these Gmail
   scopes expire after seven days. Move it to In production, then reauthorize
   the report and management profiles so the stored credentials are minted
   under the production publishing status.
2. **Google restricted-scope verification is not confirmed.** Gmail
   `gmail.readonly` and `gmail.modify` are restricted scopes. Publishing and
   OAuth verification are separate steps. For private use, Google may allow a
   small/personal-use app to remain unverified, but the unverified warning and
   user limit remain. For distribution, complete the applicable OAuth
   verification and any required security assessment. Disclose accurately that
   mail-derived summaries are delivered to Discord; do not characterize this as
   local-only processing.
3. **Management credentials are not in the hourly health map.** The current
   `credential-health.py` checks only `gmail.json` and `microsoft.json`, not
   `gmail-management.json` or `microsoft-management.json`. Add explicit
   management-profile health checks before relying on approval-gated mutations
   unattended.
4. **Refresh writes need concurrency protection.** Host health checks and
   container mail runs share credential files. Add a per-credential lock and
   atomic replace (write a mode-0600 temporary file, fsync, rename) around
   refresh/update before treating concurrent production operation as hardened.
   This avoids a process interruption or overlapping refresh from losing a
   newly rotated Microsoft refresh token.
5. **The OAuth console/app registration state has not been independently
   verified.** Check the Google publishing/verification state and Microsoft
   supported account type/public-client setting in their portals.
6. **The Microsoft script requests identity scopes too.** It currently asks
   for `openid profile email` in addition to `offline_access` and the mail
   permission. The mail collector does not appear to need identity claims;
   confirm that, then remove unused identity scopes and their allowlist entries
   before reconsenting if the narrowest possible grant is required.

## Google OAuth: required console actions

This assistant authenticates a consumer Gmail account using an installed/desktop
OAuth client and a localhost redirect. Do not switch it to a web client or add a
client secret to source control.

1. In Google Cloud Console, select the project used by the stored desktop client.
2. Under **Google Auth Platform → Audience**, confirm **External** for a
   consumer Gmail account. Under **Branding**, set the real app name, support
   contact, and developer contact. Add the required verified domains, home page,
   and privacy-policy URL if the verification path requires them.
3. Under **Data Access**, list only the scopes needed by the deployment:
   - Report: `https://www.googleapis.com/auth/gmail.readonly`
   - Separate management profile, only if mutations are enabled:
     `https://www.googleapis.com/auth/gmail.modify`
4. Under **Audience / Publishing status**, change **Testing** to **In
   production**. Testing status is the specific avoidable seven-day refresh
   token expiry risk for these non-basic Gmail scopes. “In production” does not
   itself mean Google has verified the app.
5. For use beyond the applicable personal/small-user exception, submit the
   OAuth verification request for the restricted Gmail scopes. Provide a
   truthful explanation of why each scope is needed, a consent-flow demo, and
   the requested privacy-policy/brand information. Ask Google whether a
   restricted-scope security assessment applies to this deployment: the
   workflow sends mail-derived summaries to Discord, a third-party service.
   Do not represent that data flow as on-device-only.
6. Keep the existing **Desktop app** OAuth client. The client ID is public;
   the downloaded client JSON includes a client secret, so keep the file and
   stored copy private as deployment configuration. A desktop OAuth client
   secret is not a strong confidential-client boundary, even when its local
   file is mode 0600.

### Reissue Google credentials after publishing

After the console change (and after verification/approval if required), mint
fresh credentials for each enabled profile. Do not replace one profile with the
other:

```bash
export PERSONAL_ASSISTANT_DATA_DIR="${PERSONAL_ASSISTANT_DATA_DIR:-$HOME/.hermes/personal-assistant-data}"
cd /path/to/personal-digital-assistant

python3 scripts/google-gmail-oauth.py --auth-url
# Complete consent, then pass the full localhost redirect URL:
python3 scripts/google-gmail-oauth.py --auth-code 'PASTE_COMPLETE_REDIRECT_URL'
python3 scripts/google-gmail-oauth.py --check
python3 scripts/validate-mail-credentials.py --source gmail

# Only when Gmail management is deliberately enabled and gmail.modify was added
# to the consent-screen scope declaration:
python3 scripts/google-gmail-oauth.py --profile management --auth-url
python3 scripts/google-gmail-oauth.py --profile management \
  --auth-code 'PASTE_COMPLETE_REDIRECT_URL'
python3 scripts/google-gmail-oauth.py --profile management --check
python3 scripts/validate-mail-credentials.py --source gmail --profile management
```

The script uses PKCE, `access_type=offline`, `prompt=consent`, and checks the
returned scope set. The authorization code is short-lived and single-use; do
not put it in logs or shell history. A new Google grant can invalidate an older
refresh token in some account/client-limit or security scenarios, so avoid
repeatedly reauthorizing once the production token is working.

Google refresh tokens can still stop working if the user revokes the grant,
the token is unused for an extended period (Google documents six months),
security/password changes affect a Gmail-scoped grant, an account/admin policy
revokes it, or provider token limits are reached. Production publishing
removes the Testing seven-day condition; it does not make a token irrevocable.

## Microsoft OAuth: required app registration actions

Microsoft does **not** have Google's Testing/In production consent-screen
publishing switch for this device-code public-client flow. For the current
single Hotmail account:

1. In Microsoft Entra admin center, open the app registration used by the
   configured client ID.
2. Under **Authentication**, confirm **Allow public client flows = Yes** so
   device-code authentication is allowed. This is a native/public client; do
   not create or distribute a client secret.
3. Under **Supported account types**, include **Personal Microsoft accounts**.
   For only a consumer Hotmail account, the personal-accounts-only choice is the
   least-privilege option. Use an organization-plus-personal audience only if
   organizational accounts are genuinely required.
4. Under **API permissions → Microsoft Graph → Delegated permissions**, retain
   only `Mail.Read` for reporting and add `Mail.ReadWrite` only for the separate
   management profile. `offline_access` is requested by the authorization
   protocol for refresh-token support; do not add `Mail.Send`.
5. Do not add a client secret, application permissions, or unrelated Graph
   permissions. A personal Microsoft account owner completes user consent in
   the device-code flow. Publisher verification is mainly relevant when
   distributing/trusting a multitenant app; it is not a refresh-token lifetime
   switch for this one-user MSA configuration.

### Reissue Microsoft credentials

Use the same client ID already configured for this app. For the personal
Hotmail account, use tenant `consumers`:

```bash
export PERSONAL_ASSISTANT_DATA_DIR="${PERSONAL_ASSISTANT_DATA_DIR:-$HOME/.hermes/personal-assistant-data}"
cd /path/to/personal-digital-assistant

python3 scripts/microsoft-mail-oauth.py \
  --client-id 'YOUR_APPLICATION_CLIENT_ID' --tenant consumers --auth
python3 scripts/microsoft-mail-oauth.py --check
python3 scripts/validate-mail-credentials.py --source microsoft

# Only when Microsoft management is deliberately enabled:
python3 scripts/microsoft-mail-oauth.py --profile management \
  --client-id 'YOUR_APPLICATION_CLIENT_ID' --tenant consumers --auth
python3 scripts/microsoft-mail-oauth.py --profile management --check
python3 scripts/validate-mail-credentials.py \
  --source microsoft --profile management
```

Complete the device-code consent while the command is polling. The resulting
credential must contain `offline_access`, the exact profile mail permission,
a refresh token, and mode `0600`.

Microsoft refresh tokens are renewable credentials, not permanent credentials.
Microsoft returns a replacement refresh token during refresh; this project
persists a returned replacement. Microsoft documents default refresh-token
lifetimes (commonly 90 days for native/public clients), but account, tenant,
Conditional Access/session policies, sign-in requirements, user revocation,
and risk controls can require earlier reauthentication. Do not rely on a fixed
lifetime or attempt to solve policy-driven revocation by repeatedly prompting
for consent.

## Runtime requirements for both providers

1. Keep the Mac/host and launchd supervisor running and able to reach the token
   endpoints. If the machine is asleep or offline for a long period, no
   background health check can refresh a token while it is unavailable.
2. Keep hourly forced refresh checks, but extend them to **each enabled profile**
   (report and management). If a provider refresh fails, retain the existing
   retry/alert behavior and require an operator to reauthorize; never silently
   drop back to reduced scopes or disable the source.
3. Protect token writes with a per-file lock and atomic mode-0600 replacement
   because host health checks and the Docker container use the same persistent
   files. Back up the data directory only through the encrypted backup path and
   verify restore procedures.
4. On renewal, preserve any newly returned refresh token, update access-token
   expiry, and keep the precise scope set. Never print tokens, device codes,
   authorization URLs containing state, or full token endpoint responses.
5. After provider configuration, verify each enabled profile using its
   `--check` and `validate-mail-credentials.py` command. Then force a refresh
   through the runtime and verify success/recovery through health status without
   exposing credentials. Exercise restart/recovery and alert delivery.
6. Handle `invalid_grant`, revoked consent, password/security changes, account
   policy changes, and a missing credential as **reauthorization-required**
   states. Send an operator alert and give the exact local command; do not let
   an LLM handle credentials.

## Official references

- Google OAuth refresh-token behavior and expiration:
  <https://developers.google.com/identity/protocols/oauth2#expiration>
- Google OAuth app verification:
  <https://support.google.com/cloud/answer/9110914>
- Google Gmail API scopes and restricted-scope classification:
  <https://developers.google.com/gmail/api/auth/scopes>
- Microsoft identity platform refresh tokens:
  <https://learn.microsoft.com/entra/identity-platform/refresh-tokens>
- Microsoft device-code flow:
  <https://learn.microsoft.com/entra/identity-platform/v2-oauth2-device-code>
- Microsoft public-client app registration:
  <https://learn.microsoft.com/entra/identity-platform/scenario-desktop-app-registration>
