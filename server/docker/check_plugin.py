# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001  (a build-time script copied into the Dockerfile's tools stage, not a package)
"""Build-time check and pruning of the bgutil yt-dlp plugin zip (tools stage only; D13).

    python -I check_plugin.py ZIP VERSION OUT

fetch.py has already checked the SHA-256. This script:
- requires the upstream zip to hold exactly `UPSTREAM_ENTRIES`. A new, renamed or missing file
  stops the build, so a version bump gets reviewed.
- requires the plugin to report the pinned VERSION, the same as the provider image in
  compose.yaml (the plugin warns when they differ).
- writes OUT with only `KEEP`: the shared base module and the HTTP provider. The script
  provider (`bgutil:script-node`/`script-deno`, which would run a JavaScript runtime itself) is
  left out, so only the HTTP provider can ever run. Entry dates are fixed, so builds are
  reproducible.

Exit code 1 on any mismatch.
"""

import re
import sys
import zipfile

BASE = "yt_dlp_plugins/extractor/getpot_bgutil.py"
HTTP_PROVIDER = "yt_dlp_plugins/extractor/getpot_bgutil_http.py"
SCRIPT_PROVIDER = "yt_dlp_plugins/extractor/getpot_bgutil_script.py"
DIRS = ("yt_dlp_plugins/", "yt_dlp_plugins/extractor/")
UPSTREAM_ENTRIES = frozenset({*DIRS, BASE, HTTP_PROVIDER, SCRIPT_PROVIDER})
KEEP = (*DIRS, BASE, HTTP_PROVIDER)
FIXED_DATE = (2026, 1, 1, 0, 0, 0)
EXPECTED_ARGS = 4


def check(path: str, version: str, out: str) -> str:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != UPSTREAM_ENTRIES:
            unexpected = sorted(set(names) ^ UPSTREAM_ENTRIES)
            raise SystemExit(f"{path}: entries differ from the reviewed list: {unexpected}")
        files = {name: archive.read(name) for name in KEEP if not name.endswith("/")}
    found = re.search(r"^__version__ = '([^']+)'$", files[BASE].decode("utf-8"), re.M)
    if found is None or found.group(1) != version:
        reported = found.group(1) if found else "none"
        raise SystemExit(f"{path}: plugin version {reported}, expected {version}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as pruned:
        for name in KEEP:
            info = zipfile.ZipInfo(name, FIXED_DATE)
            info.external_attr = (0o40755 if name.endswith("/") else 0o100644) << 16
            pruned.writestr(info, files.get(name, b""))
    return f"{out}: bgutil plugin {version}, HTTP provider only ({len(KEEP)} entries)\n"


def main(argv: list[str]) -> None:
    if len(argv) != EXPECTED_ARGS:
        raise SystemExit(__doc__)
    sys.stdout.write(check(argv[1], argv[2], argv[3]))


if __name__ == "__main__":
    main(sys.argv)
