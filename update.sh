#!/bin/sh
set -eu

APP_NAME="${APP_NAME:-$(basename "$PWD")}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.yml}"
SERVICE_NAME="${SERVICE_NAME:-$APP_NAME}"
CONTAINER_NAME="${CONTAINER_NAME:-$SERVICE_NAME}"

has_build=0
has_image=0
if [ -f "$COMPOSE_FILE" ]; then
  if grep -Eq "^[[:space:]]*build:" "$COMPOSE_FILE"; then
    has_build=1
  fi
  if grep -Eq "^[[:space:]]*image:" "$COMPOSE_FILE"; then
    has_image=1
  fi
fi

if [ "$has_image" -eq 1 ]; then
  docker compose -f "$COMPOSE_FILE" pull || true
fi
if [ "$has_build" -eq 1 ]; then
  docker compose -f "$COMPOSE_FILE" build --no-cache --pull
fi

docker compose -f "$COMPOSE_FILE" up -d --force-recreate

