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

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

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
    log_level: LogLevel = "INFO"
    shutdown_timeout_s: int = 10
    worker_token: SecretStr | None = None
    # Test stack only: the fake catalog and fake downloader instead of YouTube Music.
    fake_youtube: bool = False

    @property
    def database_file(self) -> Path:
        return self.database_path or self.data_dir / "ultimatetunes.db"
