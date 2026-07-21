#!/bin/sh
set -eu

APP_NAME="${APP_NAME:-$(basename "$PWD")}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.yml}"
SERVICE_NAME="${SERVICE_NAME:-$APP_NAME}"
CONTAINER_NAME="${CONTAINER_NAME:-$SERVICE_NAME}"

docker compose -f "$COMPOSE_FILE" stop "$SERVICE_NAME"

