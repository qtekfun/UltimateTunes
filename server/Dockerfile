# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# One image, two services: `api` (default) and `worker`; `migrate` runs before the api.
# Build from the repository root: docker build -f server/Dockerfile .
# Runs as non-root with a read-only root filesystem (/tmp as tmpfs).
# Worker tools (SPEC §6 and §11, spike T03c): Debian's ffmpeg, Deno (pinned version and SHA-256
# per architecture) and a yt-dlp seed zipapp whose SHA2-256SUMS is checked with gpg against the
# pinned yt-dlp release key. The live yt-dlp sits in the /opt/ytdlp volume, where the worker
# installs verified updates (T08); /opt/ytdlp-seed is the read-only copy it starts from.
# The optional PO token plugin (bgutil, D13) sits read-only in /opt/ytdlp-plugins, pinned by version
# and SHA-256; the worker loads it only when UT_YTDLP_POT_PROVIDER_URL is set.

FROM ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 AS uv

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

# Tools stage (not shipped): fetches with Python's urllib (no curl | sh) and fails closed on any
# hash, signature or fingerprint mismatch (server/docker/tools.sh). Bump a version together with
# its SHA-256 values from the upstream release: Deno's deno-<triple>.zip.sha256sum files, and the
# `yt-dlp` line of yt-dlp's signed SHA2-256SUMS. The bgutil plugin has no upstream checksum: its
# SHA-256 was taken from the release zip, whose files were compared with the tag's sources
# (D13). BGUTIL_VERSION must equal the pot-provider image tag in compose.yaml (a test checks it).
FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS tools
ARG TARGETARCH
ARG DENO_VERSION=2.9.7
ARG DENO_SHA256_AMD64=c6527f24f4b16031d3ae4fa9f658d5f11534c8d84ce7dc8502420280919c3490
ARG DENO_SHA256_ARM64=c832298b1ad4422481334855f6003e0f54145762c5a134f20a489511d2f65bbf
ARG YTDLP_SEED_VERSION=2026.08.19
ARG YTDLP_SEED_SHA256=1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6
# "Simon Sawicki (yt-dlp signing key)"; server/docker/yt-dlp-public.key must be exactly this key.
ARG YTDLP_SIGNER_FPR="AC0C BBE6 848D 6A87 3464 AF4E 57CF 6593 3B5A 7581"
ARG BGUTIL_VERSION=2.0.0
ARG BGUTIL_PLUGIN_SHA256=bce874dfa25896c2798e0f4f8147b7b22e785479eb1e459ab232bf2506c95016
RUN apt-get update \
    && apt-get install -y --no-install-recommends gnupg gpgv \
    && rm -rf /var/lib/apt/lists/*
COPY server/docker/fetch.py server/docker/check_plugin.py server/docker/tools.sh server/docker/yt-dlp-public.key /tools/
RUN sh /tools/tools.sh

FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
# ffmpeg: ReplayGain and the M4A faststart remux (T09). gpgv: yt-dlp update signatures (T08).
# pip is not needed at runtime (the venv is complete) and carries its own vendored libraries.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg gpgv \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip /usr/local/lib/python3.13/site-packages/pip-* \
        /usr/local/lib/python3.13/ensurepip/_bundled /usr/local/bin/pip /usr/local/bin/pip3* \
    && groupadd --gid 10001 tunes \
    && useradd --uid 10001 --gid tunes --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin tunes \
    && mkdir -p /data /music /staging /opt/ytdlp \
    && chown tunes:tunes /data /music /staging /opt/ytdlp
COPY --from=tools /out/bin/deno /usr/local/bin/deno
COPY --from=tools /out/share/ /usr/local/share/ultimatetunes/
COPY --from=tools /out/ytdlp-seed/ /opt/ytdlp-seed/
COPY --from=tools /out/ytdlp-plugins/ /opt/ytdlp-plugins/
COPY --from=build /app/.venv /app/.venv
COPY contracts/db/migrations /app/migrations
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UT_HOST=0.0.0.0 \
    UT_PORT=8044 \
    UT_INTERNAL_PORT=8045 \
    UT_MIGRATIONS_DIR=/app/migrations \
    DENO_NO_UPDATE_CHECK=1
USER 10001:10001
# 8044: clients. 8045: the internal worker API (never publish it).
EXPOSE 8044 8045
ENTRYPOINT ["ultimatetunes"]
CMD ["api"]
