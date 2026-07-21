# Build context is the repo root (see compose.yml: build.context: .) so this
# Dockerfile can pull in the sibling geometry/ package.

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --upgrade pip && pip install -r backend/requirements.txt

COPY geometry/ ./geometry/
RUN pip install ./geometry


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system app && useradd --system --gid app --home-dir /app --create-home app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini

# Pre-create the generated-files mount point owned by `app` so that when the
# `workshopos-generated-data` named volume is first mounted here (by both the
# api and worker services), Docker initializes the volume by copying this
# directory's ownership -- otherwise a freshly-created named volume mounts as
# root:root and the non-root `app` user below can't write into it.
RUN mkdir -p /data/generated && chown -R app:app /app /data/generated
USER app

EXPOSE 8000

# No baked CMD: compose supplies `command:` per service (api / worker / migrate).
