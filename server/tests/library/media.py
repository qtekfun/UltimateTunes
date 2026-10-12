# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small audio files for library tests, generated on the fly (no real music, no ffmpeg).

- Opus: the bundled 2 s silent CC0 file of the fake downloader, with Vorbis comments.
- MP3: a run of silent MPEG-1 Layer III frame headers (128 kbps, 44.1 kHz) plus ID3 tags.
- FLAC: a STREAMINFO block only (3 s, 44.1 kHz, stereo) plus Vorbis comments and pictures.
"""

import base64
import shutil
import struct
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import mutagen.flac
import mutagen.id3
import mutagen.oggopus

import ultimatetunes.worker as worker_pkg

# mutagen has no type hints: one untyped handle for the whole module.
M: Any = mutagen

SILENCE = Path(worker_pkg.__file__).parent / "assets" / "silence.opus"
# A tiny JPEG-looking payload: covers are served as bytes, never decoded.
JPEG = b"\xff\xd8\xff\xe0" + b"cover-bytes" + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + b"embedded-cover"

Tags = Mapping[str, str | Sequence[str]]


def _values(value: str | Sequence[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def picture(data: bytes = PNG, mime: str = "image/png") -> Any:
    pic = M.flac.Picture()
    pic.data = data
    pic.mime = mime
    pic.type = 3
    return pic


def write_opus(path: Path, tags: Tags, *, cover: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SILENCE, path)
    audio = M.oggopus.OggOpus(path)
    for key, value in tags.items():
        audio[key] = _values(value)
    if cover is not None:
        audio["metadata_block_picture"] = [
            base64.b64encode(picture(cover, "image/jpeg").write()).decode("ascii")
        ]
    audio.save()
    return path


def write_mp3(path: Path, frames: Sequence[object] = (), *, count: int = 40) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = b"\xff\xfb\x90\x64" + b"\x00" * 413
    path.write_bytes(frame * count)
    tags = M.id3.ID3()
    for item in frames:
        tags.add(item)
    tags.save(path)
    return path


def mp3_tags(  # noqa: PLR0913 - the usual tags of a test song
    title: str,
    artist: str,
    album: str,
    *,
    album_artist: str | None = None,
    track: str = "1",
    year: str = "2023",
    genre: str = "Indie Pop",
    extra: Mapping[str, str] | None = None,
    recording: str | None = None,
    cover: bytes | None = None,
) -> list[object]:
    frames: list[object] = [
        M.id3.TIT2(encoding=3, text=title),
        M.id3.TPE1(encoding=3, text=artist),
        M.id3.TALB(encoding=3, text=album),
        M.id3.TRCK(encoding=3, text=track),
        M.id3.TDRC(encoding=3, text=year),
        M.id3.TCON(encoding=3, text=genre),
    ]
    if album_artist:
        frames.append(M.id3.TPE2(encoding=3, text=album_artist))
    for desc, value in (extra or {}).items():
        frames.append(M.id3.TXXX(encoding=3, desc=desc, text=value))
    if recording:
        frames.append(M.id3.UFID(owner="http://musicbrainz.org", data=recording.encode()))
    if cover:
        frames.append(M.id3.APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=cover))
    return frames


def _streaminfo(seconds: int = 3, rate: int = 44100) -> bytes:
    head = struct.pack(">HH", 4096, 4096) + bytes(6)
    packed = (rate << 44) | (1 << 41) | (15 << 36) | (rate * seconds)
    return head + packed.to_bytes(8, "big") + bytes(16)


def write_flac(path: Path, tags: Tags, *, cover: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    info = _streaminfo()
    path.write_bytes(b"fLaC" + bytes([0x80]) + len(info).to_bytes(3, "big") + info)
    audio = M.flac.FLAC(path)
    for key, value in tags.items():
        audio[key] = _values(value)
    if cover is not None:
        audio.add_picture(picture(cover))
    audio.save()
    return path
