# Provider setup required from the operator

These steps create only read-oriented credentials. Do not paste secrets into
chat or commit them to the project.

## 1. Prepare the persistent Hermes data directory

```bash
cd personal-digital-assistant
./scripts/prepare-hermes-home.sh
chmod 700 "$PERSONAL_ASSISTANT_DATA_DIR"
```

All token files will be stored under:

```text
$PERSONAL_ASSISTANT_DATA_DIR/credentials/
```

## 2. Google Gmail read-only OAuth

### Create the Google OAuth client

1. Open <https://console.cloud.google.com/projectselector2/home/dashboard>.
2. Create or select a Google Cloud project.
3. Open **APIs & Services → Library** and enable **Gmail API**.
4. Open **Google Auth Platform → Branding** and configure the app if Google
   requests the consent-screen details.
5. Add your Google account under **Audience → Test users** when the app is in
   Testing status. A Workspace administrator may need to allowlist the app.
6. Open **APIs & Services → Credentials**.
7. Choose **Create Credentials → OAuth client ID**.
8. Choose **Desktop app** and download the JSON file.

Only the Gmail read-only scope is requested by our setup script:

```text
https://www.googleapis.com/auth/gmail.readonly
```

The general Hermes Google Workspace skill is not used because its installed
setup requests broader write-capable Workspace scopes.

### Run the narrow setup

```bash
cd personal-digital-assistant
python3 scripts/google-gmail-oauth.py --client-secret /path/to/client_secret.json
python3 scripts/google-gmail-oauth.py --auth-url
```

The second command prints an authorization URL. Open it in a browser and
approve Gmail read-only access. Google may redirect to a localhost page that
does not load; copy the complete URL from the browser address bar and run:

```bash
python3 scripts/google-gmail-oauth.py --auth-code 'PASTE_THE_COMPLETE_REDIRECT_URL_HERE'
python3 scripts/google-gmail-oauth.py --check
```

The resulting file is:

```text
.../credentials/gmail.json
```

The file contains a refresh token and is mode `0600`. Keep this report
credential read-only. Management uses a separate credential so reporting
continues to have least privilege if management access is revoked.

After adding Gmail Modify to the same OAuth application, create the separate
management credential:

```bash
python3 scripts/google-gmail-oauth.py --profile management --auth-url
python3 scripts/google-gmail-oauth.py \
  --profile management \
  --auth-code 'PASTE_THE_COMPLETE_REDIRECT_URL_HERE'
python3 scripts/google-gmail-oauth.py --profile management --check
python3 scripts/validate-mail-credentials.py \
  --source gmail --profile management
```

Approve Gmail Modify in the browser flow. This creates
`credentials/gmail-management.json`; do not replace `credentials/gmail.json`.
Both files remain mode `0600`.

In Google OAuth Testing
status, refresh tokens for sensitive scopes can expire after a limited period;
for a durable unattended deployment, publish the app or have the Workspace
administrator approve it according to the organization's policy.

## 3. Microsoft Graph read-only OAuth

### Register the application

A Hotmail address is a personal Microsoft account (MSA), not an organizational
Microsoft 365 account. Use the personal-account tenant and account type.

1. Open <https://entra.microsoft.com/> and sign in with an account allowed to
   register applications.
2. Go to **Identity → Applications → App registrations → New registration**.
3. Give the app a recognizable name, such as `Personal Assistant Mail Reader`.
4. For **Supported account types**, choose **Personal Microsoft accounts** if
   the app is only for this Hotmail account. The broader option **Accounts in
   any organizational directory and personal Microsoft accounts** also works
   but is unnecessary for a single-user assistant.
5. Do not add a redirect URI. This project uses the device-code flow.
6. Select **Register** and record the **Application (client) ID**. The client
   ID is not a secret and may be passed to the local OAuth script.
7. Open **Authentication → Advanced settings** and set **Allow public client
   flows** to **Yes**. Save the change.
8. Open **API permissions → Add a permission → Microsoft Graph → Delegated
   permissions**.
9. Keep `Mail.Read` for the report credential and add `Mail.ReadWrite` for
   the separate management credential. Do not add `Mail.Send`, `User.Read`,
   calendar, contacts, files, or directory permissions.
10. Do not create a client secret. Public-client device flow does not use one.
11. Admin consent is normally not applicable to a personal Hotmail account.
    If the portal presents an administrator-consent requirement, stop and
    resolve that requirement rather than granting broader permissions.

The report profile requests these protocol scopes:

```text
Mail.Read offline_access openid profile
```

The management profile requests:

```text
Mail.ReadWrite offline_access openid profile
```

`offline_access` is required for unattended refresh-token operation. The script
rejects any returned scope outside that approved set.

### Complete device-code consent

For a Hotmail account, use the `consumers` tenant. Do not use the default
`organizations` tenant; it is for work or school accounts and will not
correctly target a personal Hotmail identity.

First export the same data directory used by the deployment:

```bash
cd personal-digital-assistant
export PERSONAL_ASSISTANT_DATA_DIR="$HOME/.hermes/personal-assistant-data"
export HERMES_AGENT_ROOT="$HOME/.hermes/hermes-agent"
```

Start the device-code flow:

```bash
python3 scripts/microsoft-mail-oauth.py \
  --client-id 'YOUR_APPLICATION_CLIENT_ID' \
  --tenant consumers \
  --auth
```

The command prints a Microsoft verification URL and a one-time device code.
Open the URL in a browser, enter the code, sign in with the Hotmail account,
review the consent screen, and approve the requested profile permission.
Keep the terminal running;
it polls Microsoft until consent completes.

The report profile stores the refreshable credential at:

```text
$PERSONAL_ASSISTANT_DATA_DIR/credentials/microsoft.json
```

For the separate management profile, run:

```bash
python3 scripts/microsoft-mail-oauth.py \
  --profile management \
  --client-id 'YOUR_APPLICATION_CLIENT_ID' \
  --tenant consumers \
  --auth
python3 scripts/microsoft-mail-oauth.py --profile management --check
python3 scripts/validate-mail-credentials.py \
  --source microsoft --profile management
```

This creates:

```text
$PERSONAL_ASSISTANT_DATA_DIR/credentials/microsoft-management.json
```

Both files are mode `0600` and tokens are never printed.

Validate the stored Microsoft file without printing tokens:

```bash
python3 scripts/microsoft-mail-oauth.py --check
python3 scripts/validate-mail-credentials.py --source microsoft
```

Confirm that the file is private:

```bash
stat -f '%A %N' "$PERSONAL_ASSISTANT_DATA_DIR/credentials/microsoft.json"
```

The permission output must be `600`.

Until Microsoft is configured, validate Gmail alone:

```bash
python3 scripts/validate-mail-credentials.py --source gmail
```

## 4. Enable Microsoft in the deployed assistant

Do not enable management actions until the OAuth and validation commands
above pass. Reporting and new-mail review remain read-only.

Rebuild the project image and Docker egress allowlist because Microsoft
requires both `graph.microsoft.com` and `login.microsoftonline.com`:

```bash
./scripts/build-pda-image.sh
PDA_RECREATE=1 ./scripts/start-pda-egress.sh
```

Then restart the assistant with both sources enabled and reinstall the
idempotent Hermes cron record:

```bash
export PDA_MAIL_SOURCES=gmail,microsoft
./scripts/install-report-cron.sh
./scripts/run-pda-container.sh
PDA_MAIL_SOURCES=gmail,microsoft ./scripts/install-launchd.sh
```

The last command persists the source selection in the launchd environment so
future container recovery keeps Microsoft enabled. Verify the container
received both sources:

```bash
docker inspect personal-assistant-hermes \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^PDA_MAIL_SOURCES='
```

Run one bounded live collection without invoking the model:

```bash
PDA_MAIL_SOURCES=gmail,microsoft \
  python3 scripts/verify-live-gmail.py
```

The script name is retained for compatibility, but it honors
`PDA_MAIL_SOURCES` and reports safe counts/errors only; it never prints message
bodies or tokens. Review the result for both source labels, verify that
messages remain unread, and confirm that no attachment bytes were downloaded.

## 5. What is deliberately not required

- No Gmail App Password.
- No Himalaya installation for the scheduled assistant.
- No SMTP configuration.
- No `gws` installation.
- No Google Calendar, Drive, Docs, Sheets, Contacts, Gmail send, or Gmail
  modify permissions.
- No Microsoft `Mail.ReadWrite` or `Mail.Send` permission.

## 6. Live verification after both providers are configured

The first live check will be bounded to the fixed report operation. It will
read the previous IST calendar day, leave messages unread, and request only
attachment metadata. It will not send, delete, move, label, or download an
attachment.
