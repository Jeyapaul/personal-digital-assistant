#!/bin/sh
set -eu

if [ ! -r "${HERMES_HOME}/config.yaml" ]; then
  echo "Missing ${HERMES_HOME}/config.yaml; run scripts/run-pda-container.sh first" >&2
  exit 2
fi
if [ ! -r "${HERMES_HOME}/.env" ]; then
  echo "Missing ${HERMES_HOME}/.env; Discord credentials are not configured" >&2
  exit 2
fi

mkdir -p "${HOME}" "${XDG_STATE_HOME}" "${XDG_CACHE_HOME}"

# The scheduled profile must not gain capabilities merely because a different
# command is passed to the image.
exec hermes "$@"
