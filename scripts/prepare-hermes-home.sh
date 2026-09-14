#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DATA_DIR=${PERSONAL_ASSISTANT_DATA_DIR:-$HOME/.hermes/personal-assistant-data}
mkdir -p "$DATA_DIR"
chmod 700 "$DATA_DIR"

CONFIG="$DATA_DIR/config.yaml"
if [ ! -e "$CONFIG" ]; then
  cp "$ROOT/config/hermes.yaml" "$CONFIG"
  chmod 600 "$CONFIG"
  echo "Created $CONFIG"
else
  echo "Preserved existing $CONFIG"
fi

printf '%s\n' "$DATA_DIR"
