#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DATA_DIR=${PERSONAL_ASSISTANT_DATA_DIR:-$HOME/.hermes/personal-assistant-data}

"$ROOT/scripts/prepare-hermes-home.sh" >/dev/null
if [ ! -f "$DATA_DIR/.env" ]; then
  echo "Discord is not configured. Run scripts/discord-setup.py first." >&2
  exit 2
fi

cd "$ROOT"
export HERMES_HOME="$DATA_DIR"
export PERSONAL_ASSISTANT_DATA_DIR="$DATA_DIR"
export PDA_MAIL_SOURCES="${PDA_MAIL_SOURCES:-gmail,microsoft}"
export HERMES_ENABLE_PROJECT_PLUGINS=1
export HERMES_TIMEZONE=Asia/Kolkata
HERMES_PYTHON=${HERMES_PYTHON:-$ROOT/scripts/hermes-host-python.sh}
exec "$HERMES_PYTHON" "$HOME/.hermes/hermes-agent/hermes" gateway "$@"
