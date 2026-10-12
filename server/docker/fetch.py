# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001  (a build-time script copied into the Dockerfile's tools stage, not a package)
"""Build-time downloader for server/Dockerfile (tools stage only, never shipped).

    python -I fetch.py URL DEST [SHA256]

Downloads one https URL (standard library only: no curl, no shell pipes) with a timeout and a
size cap. With SHA256 the file must match it, or nothing is written and the exit code is 1.
Without SHA256 the caller must verify the file some other way (the yt-dlp checksum list is
verified with gpgv right after).
"""

import hashlib
import string
import sys
import urllib.request
from pathlib import Path

MAX_BYTES = 256 * 1024 * 1024
TIMEOUT_S = 60
CHUNK = 1024 * 1024
SHA256_HEX_LEN = 64
ARGS_WITHOUT_HASH = 3
ARGS_WITH_HASH = 4


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follows redirects (GitHub release assets redirect to a CDN) but never to plain http."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]  # noqa: PLR0913, PLR0917 (stdlib signature)
        if not newurl.startswith("https://"):
            raise SystemExit(f"refusing redirect to non-https URL: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpsOnlyRedirects)


def fetch(url: str, dest: Path, expected: str | None) -> str:
    if not url.startswith("https://"):
        raise SystemExit(f"refusing non-https URL: {url}")
    if expected is not None and (
        len(expected) != SHA256_HEX_LEN or not set(expected) <= set(string.hexdigits.lower())
    ):
        raise SystemExit(f"not a lowercase SHA-256: {expected}")

    digest = hashlib.sha256()
    data = bytearray()
    with _OPENER.open(url, timeout=TIMEOUT_S) as resp:  # https only, redirects included
        while chunk := resp.read(CHUNK):
            data += chunk
            if len(data) > MAX_BYTES:
                raise SystemExit(f"{url}: larger than {MAX_BYTES} bytes")
            digest.update(chunk)

    actual = digest.hexdigest()
    if expected is not None and actual != expected:
        raise SystemExit(f"{url}: SHA-256 mismatch: expected {expected}, got {actual}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return f"{dest}: {len(data)} bytes, sha256 {actual}\n"


def main(argv: list[str]) -> None:
    if len(argv) not in (ARGS_WITHOUT_HASH, ARGS_WITH_HASH):
        raise SystemExit(__doc__)
    expected = argv[3] if len(argv) == ARGS_WITH_HASH else None
    sys.stdout.write(fetch(argv[1], Path(argv[2]), expected))


if __name__ == "__main__":
    main(sys.argv)
