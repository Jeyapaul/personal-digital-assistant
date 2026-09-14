#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DATA_DIR=${PERSONAL_ASSISTANT_DATA_DIR:-$HOME/.hermes/personal-assistant-data}

"$ROOT/scripts/prepare-hermes-home.sh" >/dev/null

if grep -q 'REPLACE_WITH_LOCAL_MODEL' "$DATA_DIR/config.yaml"; then
  echo "Set model.default in $DATA_DIR/config.yaml after probing local models." >&2
  exit 2
fi

cd "$ROOT"
export HERMES_HOME="$DATA_DIR"
export PERSONAL_ASSISTANT_DATA_DIR="$DATA_DIR"
export PDA_MAIL_SOURCES="${PDA_MAIL_SOURCES:-gmail}"
export HERMES_ENABLE_PROJECT_PLUGINS=1
export HERMES_TIMEZONE=Asia/Kolkata
exec hermes "$@"
