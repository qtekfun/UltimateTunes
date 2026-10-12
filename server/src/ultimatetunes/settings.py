# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration from environment variables (12-factor) and Docker secrets."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

# Docker secrets; pydantic-settings warns when the directory is missing (local runs, tests).
_SECRETS_DIR = Path("/run/secrets")


class Settings(BaseSettings):
    """Every setting is an `UT_*` env var; secrets may also be files in `/run/secrets`."""

    model_config = SettingsConfigDict(
        env_prefix="UT_",
        secrets_dir=_SECRETS_DIR if _SECRETS_DIR.is_dir() else None,
        extra="ignore",
        frozen=True,
    )

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
