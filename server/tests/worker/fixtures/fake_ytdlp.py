# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in for the yt-dlp zipapp, run by `YtDlpDownloader` as `python -I -S <this> ...`.

It never touches the network. It reads the arguments the real command line passes
(`--paths home:<dir>`, `--extractor-args`, the URL after `--`) and replays output in the
shape recorded from yt-dlp (spike T03c): `UTP` progress lines on stderr (yt-dlp is quiet
because of `--print`), log lines, then the `UTF` result line on stdout. The video id picks the
scenario; every id is invented.
"""

import json
import sys
import time
from pathlib import Path
from typing import NoReturn

AUDIO = b"\x1aE\xdf\xa3" + bytes(range(256)) * 16  # a WebM magic number, then filler


def arg_after(args: list[str], flag: str, prefix: str = "") -> str:
    for i, value in enumerate(args[:-1]):
        if value == flag and args[i + 1].startswith(prefix):
            return args[i + 1][len(prefix) :]
    raise SystemExit(2)


def out(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def err(text: str) -> None:
    sys.stderr.write(text + "\n")
    sys.stderr.flush()


def emit_progress(  # noqa: PLR0913 - the fields of one recorded line
    status: str, done: int, total: int | None, *, part: Path, final: Path, fmt: str, ext: str
) -> None:
    progress: dict[str, object] = {
        "status": status,
        "downloaded_bytes": done,
        "tmpfilename": str(part),
        "filename": str(final),
    }
    if total is not None:
        progress["total_bytes"] = total
    info = {"format_id": fmt, "ext": ext, "acodec": "opus", "filesize": total}
    err("UTP " + json.dumps(progress) + "\t" + json.dumps(info))


def fail(message: str, code: int = 1) -> NoReturn:
    err(f"ERROR: [youtube] {message}")
    raise SystemExit(code)


def main(args: list[str]) -> None:  # noqa: PLR0912 - one branch per scenario
    if args == ["--version"]:
        out("2026.08.19")
        return
    video = args[-1].rsplit("=", 1)[-1]
    clients = arg_after(args, "--extractor-args", "youtube:player_client=")
    out_dir = Path(arg_after(args, "--paths", "home:"))
    err(f"[youtube] Extracting URL: https://www.youtube.com/watch?v={video}")
    err("WARNING: [youtube] a harmless warning")
    if video == "GoneVideo01":
        fail(f"{video}: Video unavailable. This video has been removed by the uploader")
    if video == "BotWall0001":
        fail(f"{video}: Sign in to confirm you're not a bot")
    if video == "UsageError1":
        raise SystemExit(2)
    if video == "HangForever":
        time.sleep(60)
    if video.startswith("Ladder") and clients == "default":
        fail(f"{video}: Requested format is not available")
    # The abuse limits, as yt-dlp applies them: a skipped video exits 0 without a word (the
    # screen is quiet because of `--print`).
    duration = 4000.0 if video == "TooLongVid1" else 2.5
    max_duration = float(arg_after(args, "--match-filter", "duration<="))
    max_bytes = int(arg_after(args, "--max-filesize"))
    if duration > max_duration:
        return
    audio = AUDIO * 8 if video in ("HugeFile001", "GrowsHuge01") else AUDIO
    if video == "HugeFile001" and len(audio) > max_bytes:
        return
    fmt, ext = ("140", "m4a") if video == "M4aAudio001" else ("251", "webm")
    if video == "MkvFormat01":
        ext = "mkv"
    final = out_dir / f"{video}.{ext}"
    part = Path(f"{final}.part")
    if video == "DotDotName1":
        final = out_dir / ".."
    if video == "EscapeDir01":
        part = out_dir.parent / "elsewhere.part"
    total = None if video in ("NoSizeKnown", "GrowsHuge01") else len(audio)
    step = len(audio) // 4
    with part.open("wb") as file:
        for done in range(step, len(audio) + 1, step):
            file.write(audio[done - step : done])
            file.flush()
            emit_progress("downloading", done, total, part=part, final=final, fmt=fmt, ext=ext)
            if video == "DiesMidway1":
                fail(f"{video}: HTTP Error 403: Forbidden")
            time.sleep(0.01)
    part.rename(final)
    emit_progress("finished", len(audio), total, part=final, final=final, fmt=fmt, ext=ext)
    if video == "NoResultL01":
        return
    result = {
        "id": video,
        "format_id": fmt,
        "ext": ext,
        "acodec": "opus",
        "filesize": total,
        "duration": duration,
        "filepath": str(final),
    }
    out("UTF " + json.dumps(result))


if __name__ == "__main__":
    main(sys.argv[1:])
