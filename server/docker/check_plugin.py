# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001  (a build-time script copied into the Dockerfile's tools stage, not a package)
"""Build-time check of the bgutil yt-dlp plugin zip (tools stage only, never shipped; D13).

    python -I check_plugin.py ZIP VERSION

The SHA-256 was already checked by fetch.py. This makes sure the zip has the layout yt-dlp's
`--plugin-dirs` loads (every entry under `yt_dlp_plugins/`, no absolute or `..` path, the HTTP
provider present) and that the plugin reports the pinned VERSION, the same as the provider image
in compose.yaml (the plugin warns when they differ). Exit code 1 on any mismatch.
"""

import re
import sys
import zipfile
from pathlib import PurePosixPath

PREFIX = "yt_dlp_plugins/"
HTTP_PROVIDER = "yt_dlp_plugins/extractor/getpot_bgutil_http.py"
BASE = "yt_dlp_plugins/extractor/getpot_bgutil.py"
EXPECTED_ARGS = 3


def check(path: str, version: str) -> str:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for name in names:
            parts = PurePosixPath(name).parts
            if not name.startswith(PREFIX) or name.startswith("/") or ".." in parts:
                raise SystemExit(f"{path}: unexpected entry {name!r}")
        if HTTP_PROVIDER not in names or BASE not in names:
            raise SystemExit(f"{path}: the bgutil HTTP provider is missing")
        source = archive.read(BASE).decode("utf-8")
    found = re.search(r"^__version__ = '([^']+)'$", source, re.M)
    if found is None or found.group(1) != version:
        reported = found.group(1) if found else "none"
        raise SystemExit(f"{path}: plugin version {reported}, expected {version}")
    return f"{path}: bgutil plugin {version}, {len(names)} entries\n"


def main(argv: list[str]) -> None:
    if len(argv) != EXPECTED_ARGS:
        raise SystemExit(__doc__)
    sys.stdout.write(check(argv[1], argv[2]))


if __name__ == "__main__":
    main(sys.argv)
