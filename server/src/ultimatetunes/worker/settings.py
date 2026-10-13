# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the worker role (`UT_*` env vars). Owner: PLAN T08.

The yt-dlp paths default to the image layout of spike T03c (SPEC section 11): the live zipapp
in the `/opt/ytdlp` volume, a verified seed copy in the image (`/opt/ytdlp-seed/yt-dlp`), the
pinned yt-dlp release key as a gpgv keyring, and Deno as the JS runtime.

Optional PO token provider (decision D13, 2026-10-13): `UT_YTDLP_POT_PROVIDER_URL` points yt-dlp's
bgutil plugin (baked into the image under `/opt/ytdlp-plugins`) at the `pot-provider` container.
Unset, yt-dlp runs exactly as before (no plugin directory at all).
"""

import ipaddress
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from ultimatetunes.settings import AreaSettings

# yt-dlp player clients, comma separated (`--extractor-args youtube:player_client=...`).
CLIENTS_PATTERN = r"^[a-z0-9_]+(,[a-z0-9_]+)*$"
# Fingerprint of the yt-dlp release signing key (spike T03c; the Dockerfile pins the same
# one), written in gpg's groups of four and compared without spaces.
YTDLP_SIGNER = "AC0C BBE6 848D 6A87 3464 AF4E 57CF 6593 3B5A 7581"
YTDLP_KEY_FINGERPRINT = YTDLP_SIGNER.replace(" ", "")
# A container or service name on a Docker network: one DNS label that starts with a letter, so
# it can never be read as a number or hex IPv4 address (`inet_aton`) and never needs public DNS.
_SERVICE_NAME = re.compile(r"^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")


# The only address ranges a PO token provider may live in: private and loopback, nothing else
# (no link-local metadata services, no IPv4-mapped or 6to4 forms of other addresses).
INTERNAL_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "::1/128",
        "fc00::/7",
    )
)
# Characters that must never reach yt-dlp's `--extractor-args` (its separators, and `%` of an
# IPv6 zone id or an escape).
UNSAFE_URL_CHARS = frozenset(",;%")


def _internal_host(host: str) -> str | None:
    """The canonical form of a Docker service name or an address inside `INTERNAL_NETWORKS`, or
    None. IPv6 zone ids (`%...`) are refused."""
    if "%" in host:
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host if _SERVICE_NAME.fullmatch(host) else None
    if any(address in net for net in INTERNAL_NETWORKS):
        return str(address)
    return None


def internal_base_url(value: str) -> str:
    """The canonical `http(s)://host[:port]` of a service on an internal network, or ValueError.

    Only a scheme, a host and a port: no credentials, path, query or fragment, and a host that
    is a single-label service name or a private/loopback address, so the URL can only lead to a
    container next to the worker. Rebuilt from its parts, so it never carries `,`, `;` (the
    separators of yt-dlp's `--extractor-args`) or `%` (IPv6 zone ids are refused). Errors never
    echo the value.
    """
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError as exc:
        raise ValueError("not a valid URL") from exc
    if parts.scheme not in ("http", "https"):
        raise ValueError("the URL must be http or https")
    if parts.username is not None or parts.password is not None:
        raise ValueError("the URL must not carry credentials")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("the URL must be a bare base URL (no path, query or fragment)")
    host = _internal_host(parts.hostname or "")
    if host is None:
        raise ValueError("the host must be a service name on a Docker network or a private address")
    if port == 0:
        raise ValueError("the URL must not use port 0")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    url = f"{parts.scheme}://{netloc}"
    if UNSAFE_URL_CHARS & set(url):  # a last guard, whatever the host check lets through
        raise ValueError("the URL contains characters yt-dlp's extractor arguments cannot carry")
    return url


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
    # PO token provider (D13): the base URL of the bgutil HTTP server (`pot-provider` in
    # compose.yaml, reached as `http://bgutil:4416`). Unset or empty: no plugin is loaded.
    ytdlp_pot_provider_url: str | None = None
    # Where the image keeps the pinned bgutil plugin zip (read-only, Dockerfile).
    ytdlp_plugin_dir: Path = Path("/opt/ytdlp-plugins")
    # Optional YouTube cookies (approved 2026-10-13, superseding SPEC §11's "no cookies in v1"):
    # the path of a Netscape/Mozilla `cookies.txt` exported from a **throwaway** account,
    # normally the read-only Docker secret `ut_ytdlp_cookies` at `/run/secrets/ut_ytdlp_cookies`.
    # Unset or empty: no cookies, exactly as before. The file content is an account credential:
    # the worker never hands this read-only file to yt-dlp (yt-dlp rewrites the cookies file in
    # place), but copies it to a private 0600 temp per download and deletes it afterwards, and
    # the path must sit inside an allowed directory (`/run/secrets`); see `worker/ytdlp.py`.
    ytdlp_cookies_file: Path | None = None

    @field_validator("ytdlp_pot_provider_url")
    @classmethod
    def _internal_provider(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return internal_base_url(value)

    @field_validator("ytdlp_cookies_file", mode="before")
    @classmethod
    def _no_empty_cookies(cls, value: object) -> object:
        # An unset or blank value means "no cookies"; `Path("")` would otherwise become `.`.
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value
