#!/bin/sh
set -eu

# The original Hermes venv is Python 3.11 and links _sqlite3 to macOS's
# vulnerable SQLite 3.40.1. Homebrew Python 3.14 links SQLite 3.53.4. Reuse
# the reviewed Hermes package set through PYTHONPATH while executing Hermes with
# the newer interpreter. This wrapper accepts the same arguments as python.
PYTHON=${PDA_HOST_PYTHON:-/opt/homebrew/bin/python3.14}
HERMES_ROOT=${HERMES_AGENT_ROOT:-$HOME/.hermes/hermes-agent}
SITE_PACKAGES=$(find "$HERMES_ROOT/venv/lib" -maxdepth 2 -type d -name site-packages -print -quit)
if [ -z "$SITE_PACKAGES" ] || [ ! -f "$HERMES_ROOT/hermes" ]; then
  echo "Hermes installation is incomplete: $HERMES_ROOT" >&2
  exit 2
fi
unset PYTHONHOME
export PYTHONPATH="$SITE_PACKAGES:$HERMES_ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" "$@"
