#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
HERMES_PYTHON=${HERMES_PYTHON:-$HOME/.hermes/hermes-agent/venv/bin/python}
exec "$HERMES_PYTHON" "$ROOT/scripts/verify-phase1.py"
