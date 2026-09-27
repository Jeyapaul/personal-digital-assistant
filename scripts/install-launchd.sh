#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DATA_DIR=${PERSONAL_ASSISTANT_DATA_DIR:-$HOME/.hermes/personal-assistant-data}
MAIL_SOURCES=${PDA_MAIL_SOURCES:-gmail,microsoft}
MODEL=${PDA_MODEL:-pda-qwen30}
LABEL=com.personal-assistant.hermes
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$DATA_DIR/lifecycle"
chmod 700 "$DATA_DIR/lifecycle"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$ROOT/scripts/lifecycle-supervisor.sh</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key><string>$HOME</string>
    <key>PERSONAL_ASSISTANT_DATA_DIR</key><string>$DATA_DIR</string>
    <key>PDA_IMAGE</key><string>personal-assistant-hermes:0.20.6</string>
    <key>PDA_CONTAINER</key><string>personal-assistant-hermes</string>
    <key>PDA_EGRESS_CONTAINER</key><string>personal-assistant-egress</string>
    <key>PDA_INTERNAL_NETWORK</key><string>personal-assistant-internal</string>
    <key>PDA_EGRESS_NETWORK</key><string>personal-assistant-egress-out</string>
    <key>PDA_MAIL_SOURCES</key><string>$MAIL_SOURCES</string>
    <key>PDA_MAIL_MUTATION_ENABLED</key><string>true</string>
    <key>PDA_APPROVAL_EXPIRY_HOURS</key><string>0</string>
    <key>PDA_MODEL</key><string>$MODEL</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ExitTimeOut</key><integer>30</integer>
  <key>StandardOutPath</key><string>$DATA_DIR/lifecycle/launchd.stdout.log</string>
  <key>StandardErrorPath</key><string>$DATA_DIR/lifecycle/launchd.stderr.log</string>
</dict>
</plist>
EOF
chmod 600 "$PLIST"

DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
# bootout can leave a SIGTERMed LaunchAgent visible briefly. Wait for the
# domain entry to disappear before bootstrapping the replacement.
for _ in $(seq 1 30); do
  if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "launchd did not unload $LABEL" >&2
  exit 1
fi
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"
launchctl kickstart -k "$DOMAIN/$LABEL"
printf '%s\n' "Installed and started $LABEL"
printf '%s\n' "$PLIST"
