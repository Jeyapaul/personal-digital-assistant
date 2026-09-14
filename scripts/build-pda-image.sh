#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
IMAGE=${PDA_IMAGE:-personal-assistant-hermes:0.20.6}
HERMES_IMAGE=${HERMES_IMAGE:-nousresearch/hermes-agent:latest@sha256:da20e13cc04fb7ade2a4725255870ebb5f367ec60e89d21707d35bc09a10a934}

cd "$ROOT"
printf '%s\n' "Building $IMAGE from $HERMES_IMAGE"
docker build --pull \
  --build-arg "HERMES_IMAGE=$HERMES_IMAGE" \
  --tag "$IMAGE" \
  .
