# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration from environment variables (12-factor) and Docker secrets.

`Settings` holds what the whole server shares (paths, listener, logging, the worker token).
Each area keeps its own settings in its own module, so parallel streams never edit this file:
`<area>/settings.py` subclasses `AreaSettings` (same `UT_` prefix, same Docker secrets) and
reads its variables on its own, e.g. `worker/settings.py` (`UT_API_URL`, ...),
`streaming/settings.py` (listener caps), `admin/settings.py` (T15). Area variable names must
not clash with the ones here or with another area's.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ultimatetunes.core.netaddr import IpNetwork, parse_networks

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
MIN_WORKER_TOKEN_LENGTH = 32

# Docker secrets; pydantic-settings warns when the directory is missing (local runs, tests).
_SECRETS_DIR = Path("/run/secrets")


def settings_config() -> SettingsConfigDict:
    """`UT_*` env vars, secrets also as files in `/run/secrets`, unknown variables ignored."""
    return SettingsConfigDict(
        env_prefix="UT_",
        secrets_dir=_SECRETS_DIR if _SECRETS_DIR.is_dir() else None,
        extra="ignore",
        frozen=True,
    )


class AreaSettings(BaseSettings):
    """Base of the per-area settings (`<area>/settings.py`)."""

    model_config = settings_config()


class Settings(BaseSettings):
    """Every setting is an `UT_*` env var; secrets may also be files in `/run/secrets`."""

    model_config = settings_config()

    data_dir: Path = Path("/data")
    music_dir: Path = Path("/music")
    staging_dir: Path = Path("/staging")
    # Plain SQL migrations shipped next to the code (contracts/db/migrations in the repo).
    migrations_dir: Path = Path("/app/migrations")
    database_path: Path | None = None
    # Loopback unless told otherwise; the image sets UT_HOST=0.0.0.0 and compose decides exposure.
    host: str = "127.0.0.1"
    port: int = 8044
    # The internal worker API (`/internal/v1`) has its own listener (SECURITY.md, T22): the
    # client port never serves it and this one serves nothing else. Bound to `host` unless
    # `UT_INTERNAL_HOST` says otherwise; never publish this port (compose keeps it on the
    # internal network).
    internal_host: str | None = None
    internal_port: int = Field(default=8045, ge=1, le=65535)
    # Comma-separated CIDRs of reverse proxies whose `X-Forwarded-For` is believed (Caddy,
    # `tailscale serve` through Docker's port publishing, ...). Empty (default): nobody's, the
    # TCP peer is the client, and `/admin` refuses requests that carry forwarding headers.
    trusted_proxies: str = ""
    # Comma-separated CIDRs of the worker's network (the internal Docker network): callers from
    # there never get `/admin` or the `/readyz` detail, even though the addresses are private.
    worker_networks: str = ""
    # Largest request body the api reads (an import file is at most 1 MiB).
    max_body_bytes: int = Field(default=4 * 1024 * 1024, ge=64 * 1024)
    # Housekeeping of the api (expired cache entries, idle rate-limit buckets, cache caps).
    housekeeping_interval_s: float = Field(default=600.0, ge=0)
    # Caps of the shared `TtlCache` (`cache_entries`): oldest entries go first past either.
    cache_max_entries: int = Field(default=200_000, ge=100)
    cache_max_bytes: int = Field(default=256 * 1024 * 1024, ge=1024 * 1024)
    # Connection limits of the listeners (audit M2). Past `limit_concurrency` open connections
    # or running requests uvicorn answers 503; streams hold a connection while they play.
    # uvicorn has no request-header timeout: a public deployment puts Caddy in front
    # (`read_header`, deploy/README.md), never the api directly.
    limit_concurrency: int = Field(default=128, ge=8, le=10_000)
    internal_limit_concurrency: int = Field(default=32, ge=4, le=1_000)
    # Idle keep-alive connections are closed after this many seconds.
    keepalive_timeout_s: int = Field(default=5, ge=1, le=120)
    # Pending connections the kernel queues before refusing.
    backlog: int = Field(default=256, ge=16, le=65_535)
    # Largest request line + headers (h11), bytes.
    max_header_bytes: int = Field(default=16 * 1024, ge=4 * 1024, le=256 * 1024)
    log_level: LogLevel = "INFO"
    shutdown_timeout_s: int = 10
    # Shared by the api and the worker (Docker secret `ut_worker_token`); at least 32
    # characters (`openssl rand -hex 32`). Empty means unset: the internal API refuses everyone.
    worker_token: SecretStr | None = None
    # Test stack only: the fake catalog and fake downloader instead of YouTube Music.
    fake_youtube: bool = False

    @field_validator("worker_token")
    @classmethod
    def _long_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        if len(value.get_secret_value().strip()) < MIN_WORKER_TOKEN_LENGTH:
            raise ValueError(f"the worker token needs {MIN_WORKER_TOKEN_LENGTH}+ characters")
        return value

    @field_validator("trusted_proxies", "worker_networks")
    @classmethod
    def _valid_networks(cls, value: str) -> str:
        parse_networks(value)
        return value

    @property
    def proxy_networks(self) -> tuple[IpNetwork, ...]:
        return parse_networks(self.trusted_proxies)

    @property
    def worker_network_list(self) -> tuple[IpNetwork, ...]:
        return parse_networks(self.worker_networks)

    @property
    def internal_bind(self) -> str:
        return self.internal_host or self.host

    @property
    def database_file(self) -> Path:
        return self.database_path or self.data_dir / "ultimatetunes.db"
