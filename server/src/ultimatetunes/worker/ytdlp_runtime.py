# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The yt-dlp zipapp in the `/opt/ytdlp` volume and its self-update (spike T03c, SPEC §11).

Layout (worker only, the root filesystem stays read-only):

    /opt/ytdlp/
      current -> releases/<tag>     symlink, swapped atomically
      releases/<tag>/yt-dlp         immutable once verified
      tmp/                          downloads being verified (cleaned before each update)

- **Seed**: when the volume has no usable `current`, the verified seed copy baked into the
  image (`/opt/ytdlp-seed/yt-dlp`, pinned by SHA-256 at build time) is installed.
- **Update** (GitHub releases only, hosts approved 2026-10-12): latest tag of `yt-dlp/yt-dlp`
  (or the nightly repository) → download `yt-dlp`, `SHA2-256SUMS`, `SHA2-256SUMS.sig` over
  HTTPS from the approved hosts only, size-capped → `gpgv` against the pinned keyring, which
  must report `VALIDSIG` with the pinned fingerprint → SHA-256 of the zipapp equals its line
  in the sums → smoke test (`--version` prints the tag) → move into `releases/<tag>` → swap
  `current`. Release directories never change once in place, and a download resolves
  `current` when it starts, so an update never touches a running download. The two newest
  previous releases are kept for rollback.
"""

import hashlib
import json
import logging
import re
import secrets
import shutil
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

# Only for the type of a finished process; processes start with anyio and argument lists.
from subprocess import CompletedProcess  # nosec B404

import anyio
import httpx

from ultimatetunes.worker.settings import WorkerSettings

log = logging.getLogger(__name__)

ZIPAPP = "yt-dlp"
SUMS = "SHA2-256SUMS"
SIGNATURE = "SHA2-256SUMS.sig"
REPOS = {"stable": "yt-dlp/yt-dlp", "nightly": "yt-dlp/yt-dlp-nightly-builds"}
TAG = re.compile(r"^\d{4}\.\d{2}\.\d{2}(\.\d+)?$")
# CLAUDE.md: the only hosts the server contacts for yt-dlp updates.
ALLOWED_HOSTS = frozenset(
    {
        "api.github.com",
        "github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }
)
MAX_REDIRECTS = 5
MAX_ZIPAPP_BYTES = 50 * 1024 * 1024
MAX_SMALL_BYTES = 1024 * 1024
SUBPROCESS_TIMEOUT_S = 60.0
KEEP_PREVIOUS = 2
VALIDSIG_MIN_FIELDS = 3

ProcessRunner = Callable[[Sequence[str]], Awaitable[CompletedProcess[bytes]]]


class UpdateError(Exception):
    """The update was refused or failed; the current release stays in place."""


@dataclass(frozen=True)
class UpdateResult:
    version: str
    updated: bool


async def _run(args: Sequence[str]) -> CompletedProcess[bytes]:
    # Argument lists only (gpgv and the zipapp's --version), never a shell.
    with anyio.fail_after(SUBPROCESS_TIMEOUT_S):
        return await anyio.run_process(list(args), check=False)


class YtDlpRuntime:
    """The current zipapp, the seed install and the verified update."""

    def __init__(
        self,
        settings: WorkerSettings,
        *,
        client: httpx.AsyncClient | None = None,
        run: ProcessRunner = _run,
        python: str = sys.executable,
    ) -> None:
        self._settings = settings
        self._root = settings.ytdlp_dir
        self._client = client
        self._run = run
        self._python = python

    @property
    def current_link(self) -> Path:
        return self._root / "current"

    def current_zipapp(self) -> Path:
        return self.current_link / ZIPAPP

    def current_version(self) -> str | None:
        """The tag `current` points at, or None when nothing is installed."""
        if not self.current_zipapp().is_file():
            return None
        name = self.current_link.readlink().name
        return name if TAG.fullmatch(name) else None

    # ------------------------------------------------------------ seed

    async def ensure_installed(self) -> str:
        """Installs the image's seed copy when the volume has no usable release."""
        current = self.current_version()
        if current is not None:
            return current
        seed = self._settings.ytdlp_seed_dir / ZIPAPP
        if not seed.is_file():
            raise UpdateError("no yt-dlp in the volume and no seed in the image")
        version = await self._smoke(seed)
        tmp = self._fresh_tmp(version)
        shutil.copyfile(seed, tmp / ZIPAPP)
        self._install(tmp, version)
        log.info("yt-dlp: seed %s installed", version)
        return version

    # ------------------------------------------------------------ update

    async def update(self, *, force: bool = False) -> UpdateResult:
        """Installs the latest release of the channel when it is newer (or `force`)."""
        repo = REPOS[self._settings.ytdlp_channel]
        tag = await self._latest_tag(repo)
        current = self.current_version()
        if tag == current and not force:
            return UpdateResult(tag, updated=False)
        tmp = self._fresh_tmp(tag)
        base = f"https://github.com/{repo}/releases/download/{tag}"
        (tmp / ZIPAPP).write_bytes(await self._get(f"{base}/{ZIPAPP}", MAX_ZIPAPP_BYTES))
        (tmp / SUMS).write_bytes(await self._get(f"{base}/{SUMS}", MAX_SMALL_BYTES))
        (tmp / SIGNATURE).write_bytes(await self._get(f"{base}/{SIGNATURE}", MAX_SMALL_BYTES))
        await self._verify_signature(tmp)
        self._verify_sha256(tmp)
        version = await self._smoke(tmp / ZIPAPP)
        if version != tag:
            raise UpdateError(f"the zipapp reports {version!r}, expected {tag!r}")
        (tmp / SUMS).unlink()
        (tmp / SIGNATURE).unlink()
        self._install(tmp, tag)
        log.info("yt-dlp: updated %s -> %s", current, tag)
        return UpdateResult(tag, updated=True)

    async def _latest_tag(self, repo: str) -> str:
        body = await self._get(
            f"https://api.github.com/repos/{repo}/releases/latest", MAX_SMALL_BYTES
        )
        try:
            tag = json.loads(body)["tag_name"]
        except (ValueError, KeyError, TypeError) as exc:
            raise UpdateError("unexpected GitHub releases answer") from exc
        if not isinstance(tag, str) or not TAG.fullmatch(tag):
            raise UpdateError("unexpected release tag")
        return tag

    async def _get(self, url: str, max_bytes: int) -> bytes:
        """HTTPS GET from the approved hosts only; redirects are followed by hand so every
        hop is checked; the body is capped while it streams."""
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            for _ in range(MAX_REDIRECTS + 1):
                target = httpx.URL(url)
                if target.scheme != "https" or target.host not in ALLOWED_HOSTS:
                    raise UpdateError(f"refusing to contact {target.host or 'that host'}")
                async with client.stream("GET", target, follow_redirects=False) as response:
                    if response.is_redirect:
                        url = str(target.join(response.headers.get("location", "")))
                        continue
                    if response.status_code != httpx.codes.OK:
                        raise UpdateError(f"GitHub answered {response.status_code}")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data += chunk
                        if len(data) > max_bytes:
                            raise UpdateError("download larger than allowed")
                    return bytes(data)
            raise UpdateError("too many redirects")
        except httpx.HTTPError as exc:
            raise UpdateError(f"download failed: {type(exc).__name__}") from exc
        finally:
            if self._client is None:
                await client.aclose()

    async def _verify_signature(self, tmp: Path) -> None:
        result = await self._run(
            [
                str(self._settings.gpgv_path),
                "--status-fd",
                "1",
                "--keyring",
                str(self._settings.ytdlp_keyring),
                str(tmp / SIGNATURE),
                str(tmp / SUMS),
            ]
        )
        pinned = self._settings.ytdlp_key_fingerprint
        valid = result.returncode == 0 and any(
            # [GNUPG:] VALIDSIG <signing key fpr> ... <primary key fpr>
            len(fields) >= VALIDSIG_MIN_FIELDS
            and fields[:2] == ["[GNUPG:]", "VALIDSIG"]
            and pinned in (fields[2], fields[-1])
            for fields in (
                line.split() for line in result.stdout.decode("utf-8", "replace").splitlines()
            )
        )
        if valid:
            return
        raise UpdateError("signature of SHA2-256SUMS not valid for the pinned key")

    @staticmethod
    def _verify_sha256(tmp: Path) -> None:
        expected = None
        for line in (tmp / SUMS).read_text(encoding="utf-8", errors="replace").splitlines():
            digest, _, name = line.strip().partition(" ")
            if name.strip().lstrip("*") == ZIPAPP:
                expected = digest.lower()
        actual = hashlib.sha256((tmp / ZIPAPP).read_bytes()).hexdigest()
        if expected is None or not secrets.compare_digest(expected, actual):
            raise UpdateError("SHA-256 of the zipapp does not match SHA2-256SUMS")

    async def _smoke(self, zipapp: Path) -> str:
        result = await self._run([self._python, "-I", "-S", str(zipapp), "--version"])
        version = result.stdout.decode("utf-8", "replace").strip()
        if result.returncode != 0 or not TAG.fullmatch(version):
            raise UpdateError("the zipapp failed its smoke test")
        return version

    # ------------------------------------------------------------ files

    def _fresh_tmp(self, tag: str) -> Path:
        tmp_root = self._root / "tmp"
        shutil.rmtree(tmp_root, ignore_errors=True)
        tmp = tmp_root / f"{tag}-{secrets.token_hex(4)}"
        tmp.mkdir(parents=True)
        return tmp

    def _install(self, tmp: Path, tag: str) -> None:
        releases = self._root / "releases"
        releases.mkdir(parents=True, exist_ok=True)
        target = releases / tag
        if target.exists():
            shutil.rmtree(tmp)
        else:
            (tmp / ZIPAPP).chmod(0o444)
            tmp.rename(target)
        link_tmp = self._root / f"current.{secrets.token_hex(4)}"
        link_tmp.symlink_to(Path("releases") / tag)
        link_tmp.replace(self.current_link)
        self._prune(releases, tag)

    @staticmethod
    def _prune(releases: Path, current: str) -> None:
        others = sorted((p for p in releases.iterdir() if p.name != current), reverse=True)
        for old in others[KEEP_PREVIOUS:]:
            shutil.rmtree(old, ignore_errors=True)
