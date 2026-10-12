# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the worker role (`UT_*` env vars). Owner: PLAN T08.

The yt-dlp paths default to the image layout of spike T03c (SPEC section 11): the live zipapp
in the `/opt/ytdlp` volume, a verified seed copy in the image (`/opt/ytdlp-seed/yt-dlp`), the
pinned yt-dlp release key as a gpgv keyring, and Deno as the JS runtime.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field

from ultimatetunes.settings import AreaSettings

# yt-dlp player clients, comma separated (`--extractor-args youtube:player_client=...`).
CLIENTS_PATTERN = r"^[a-z0-9_]+(,[a-z0-9_]+)*$"
# Fingerprint of the yt-dlp release signing key (spike T03c; the Dockerfile pins the same
# one), written in gpg's groups of four and compared without spaces.
YTDLP_SIGNER = "AC0C BBE6 848D 6A87 3464 AF4E 57CF 6593 3B5A 7581"
YTDLP_KEY_FINGERPRINT = YTDLP_SIGNER.replace(" ", "")


class WorkerSettings(AreaSettings):
    # The api's internal worker API: its own listener on the internal Docker network (T22).
    api_url: str = "http://api:8045"
    # Stable id of this worker process; the hostname and pid when unset.
    worker_id: str | None = None
    # Lease asked for at claim; heartbeats come every third of it (contract).
    lease_s: int = Field(default=60, ge=15, le=300)
    # Wait before claiming again when the api is unreachable or did not say (`Retry-After`).
    poll_interval_s: float = Field(default=2.0, gt=0, le=60)
    # Long poll (issue #55): an idle claim asks the api to hold it this long and answer as
    # soon as a job is queued; 0 turns it off (poll every `Retry-After` seconds instead).
    # Under the 10 s Docker stop grace period, though a stop also abandons the claim at once.
    claim_wait_s: int = Field(default=8, ge=0, le=30)
    # Timeout of one call to the api, and how often an idempotent call is retried after a
    # transport error or a 5xx before the worker gives up on it.
    api_timeout_s: float = Field(default=10.0, gt=0, le=120)
    api_retries: int = Field(default=3, ge=0, le=10)
    # Status report (versions, admin commands) every this many seconds.
    status_interval_s: float = Field(default=300.0, gt=0)
    # Circuit breaker when YouTube blocks us (429, bot check): pause claiming, doubling up to
    # the maximum while blocks continue (spike T03c).
    blocked_pause_s: float = Field(default=1800.0, ge=0)
    blocked_pause_max_s: float = Field(default=14400.0, ge=0)
    # Pace of the fake downloader (`UT_FAKE_YOUTUBE`, test stack only): the end-to-end suite
    # (PLAN T20) slows it down so a stream is seen growing and a worker can be killed mid-download.
    fake_download_chunks: int = Field(default=8, ge=1, le=1000)
    fake_download_delay_s: float = Field(default=0.05, ge=0, le=60)

    # yt-dlp (spike T03c).
    ytdlp_dir: Path = Path("/opt/ytdlp")
    ytdlp_seed_dir: Path = Path("/opt/ytdlp-seed")
    ytdlp_keyring: Path = Path("/usr/local/share/ultimatetunes/yt-dlp-keyring.gpg")
    ytdlp_key_fingerprint: str = Field(default=YTDLP_KEY_FINGERPRINT, pattern=r"^[0-9A-F]{40}$")
    ytdlp_channel: Literal["stable", "nightly"] = "stable"
    ytdlp_auto_update: bool = True
    ytdlp_update_interval_h: float = Field(default=24.0, gt=0)
    # Bound of one whole update check (GitHub, gpgv, smoke test).
    ytdlp_update_timeout_s: float = Field(default=300.0, gt=0)
    # An extractor error triggers an update at most this often.
    ytdlp_update_on_error_min_interval_s: float = Field(default=3600.0, ge=0)
    ytdlp_player_clients: str = Field(default="default", pattern=CLIENTS_PATTERN)
    ytdlp_fallback_clients: str = Field(default="web_embedded", pattern=r"^$|" + CLIENTS_PATTERN)
    ytdlp_timeout_s: float = Field(default=600.0, gt=0)
    deno_path: Path = Path("/usr/local/bin/deno")
    gpgv_path: Path = Path("/usr/bin/gpgv")
