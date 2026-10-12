# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# One image, two services: `api` (default) and `worker`; `migrate` runs before the api.
# Build from the repository root: docker build -f server/Dockerfile .
# Runs as non-root with a read-only root filesystem (/tmp as tmpfs). ffmpeg and the JS runtime
# yt-dlp needs are added after spike T03c.

FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv

FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src/server
COPY VERSION /src/VERSION
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY server/src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
RUN groupadd --gid 10001 tunes \
    && useradd --uid 10001 --gid tunes --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin tunes \
    && mkdir -p /data /music /staging /opt/ytdlp \
    && chown tunes:tunes /data /music /staging /opt/ytdlp
COPY --from=build /app/.venv /app/.venv
COPY contracts/db/migrations /app/migrations
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UT_HOST=0.0.0.0 \
    UT_PORT=8044 \
    UT_MIGRATIONS_DIR=/app/migrations
USER 10001:10001
EXPOSE 8044
ENTRYPOINT ["ultimatetunes"]
CMD ["api"]
