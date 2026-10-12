# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cover art (`getCoverArt`, contracts/ids.md "Cover art ids").

Library covers come from `/music` through `LibraryStore`:
- `al-<album>`: the album's `cover_path`, else an image file next to its first song
  (`cover.jpg`, `folder.jpg`, ...), else the picture embedded in that song.
- `ar-<artist>`: the artist's `image_path`, else the cover of their newest album.
- `pl-<playlist>`: the cover of the first song of the playlist that has one (only for the
  owner, or anyone when the playlist is public).

Virtual ids (`yt:`, `ytalbum:`, `ytartist:`) show the catalog thumbnail. A `yt:` song already
archived shows its album cover. Thumbnails are fetched only from the catalog's URL (never a
URL from the client), over HTTPS, from the exact approved hosts, without following redirects,
only `image/*`, at most 5 MiB (counted while streaming). They are kept in a bounded disk cache
under `/data` (`CoverCache`, TTL and size cap from `LibrarySettings`). Anything that breaks a
rule is error 70; a network failure is `UpstreamUnavailable`. `size` is ignored (v1).
"""

import contextlib
import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx
import mutagen
from mutagen.flac import Picture
from mutagen.mp4 import MP4Cover
from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.clock import Clock
from ultimatetunes.core.storage import LibraryStore
from ultimatetunes.db.driver import Connection
from ultimatetunes.errors import NotFound, PathRejected, UpstreamUnavailable
from ultimatetunes.ids.resolve import tracks_for_videos
from ultimatetunes.ids.virtual import CoverId, parse_cover_id
from ultimatetunes.library.settings import LibrarySettings

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services

ALLOWED_HOSTS = frozenset(
    {"i.ytimg.com", "lh3.googleusercontent.com", "yt3.ggpht.com", "yt3.googleusercontent.com"}
)
MAX_EXTERNAL_BYTES = 5 * 1024 * 1024
# Embedded pictures larger than this are ignored (they are read into memory).
MAX_EMBEDDED_BYTES = 16 * 1024 * 1024
COVER_FILES = (
    "cover.jpg",
    "cover.jpeg",
    "cover.png",
    "cover.webp",
    "folder.jpg",
    "folder.jpeg",
    "folder.png",
    "front.jpg",
    "front.png",
)
IMAGE_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}
_SUBTYPE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,31}$")


@dataclass(frozen=True)
class Image:
    """An image to send: in memory (`data`) or a library file (`path`, `size`)."""

    content_type: str
    data: bytes | None = None
    path: str | None = None
    size: int = 0


def not_found() -> NotFound:
    return NotFound("Cover art not found")


# ---------------------------------------------------------------------- library


def _image_type(path: str) -> str | None:
    suffix = PurePosixPath(path).suffix.lower().lstrip(".")
    return IMAGE_TYPES.get(suffix)


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)


def _file(store: LibraryStore, path: str | None) -> Image | None:
    if not path:
        return None
    content_type = _image_type(path)
    if content_type is None:
        return None
    try:
        if not store.exists(path):
            return None
        return Image(content_type, path=path, size=store.size(path))
    except (PathRejected, OSError):
        return None


def _picture(audio: object) -> tuple[bytes, str] | None:
    """The first embedded picture of a mutagen file (FLAC, ID3, MP4, Ogg comments)."""
    pictures = getattr(audio, "pictures", None)
    if pictures:
        return bytes(pictures[0].data), str(pictures[0].mime)
    tags = getattr(audio, "tags", None)
    if tags is None:
        return None
    # ID3 (MP3): APIC frames.
    getall = getattr(tags, "getall", None)
    if callable(getall):
        frames = getall("APIC")
        return (bytes(frames[0].data), str(frames[0].mime)) if frames else None
    # MP4: `covr` atoms (JPEG or PNG).
    covers = tags.get("covr") if hasattr(tags, "get") else None
    if covers:
        cover = covers[0]
        png = getattr(cover, "imageformat", None) == MP4Cover.FORMAT_PNG
        mime = "image/png" if png else "image/jpeg"
        return bytes(cover), mime
    # Vorbis comments (Opus, Ogg): base64 FLAC picture blocks.
    blocks = tags.get("metadata_block_picture") if hasattr(tags, "get") else None
    if blocks:
        import base64  # noqa: PLC0415

        with contextlib.suppress(ValueError, TypeError, mutagen.MutagenError):
            picture = Picture(base64.b64decode(blocks[0]))  # type: ignore[no-untyped-call]
            return bytes(picture.data), str(picture.mime)
    return None


def embedded(store: LibraryStore, path: str) -> Image | None:
    try:
        with store.open_read(path) as handle:
            audio = mutagen.File(handle)
    except (mutagen.MutagenError, OSError, PathRejected, ValueError):
        return None
    found = _picture(audio)
    if found is None:
        return None
    data, mime = found
    if not data or len(data) > MAX_EMBEDDED_BYTES:
        return None
    if not mime.startswith("image/"):
        mime = "image/jpeg"
    return Image(mime, data=data)


def _first_song_path(conn: Connection, album_id: str) -> str | None:
    row = conn.execute(
        "SELECT path FROM tracks WHERE album_id = ? AND status = 'ready' AND path IS NOT NULL"
        " ORDER BY COALESCE(disc_number, 1), COALESCE(track_number, 0), id LIMIT 1",
        (album_id,),
    ).fetchone()
    return None if row is None else str(row["path"])


def album_cover(conn: Connection, store: LibraryStore, album_id: str) -> Image | None:
    row = conn.execute("SELECT cover_path FROM albums WHERE id = ?", (album_id,)).fetchone()
    if row is None:
        return None
    found = _file(store, _opt_str(row["cover_path"]))
    if found is not None:
        return found
    song = _first_song_path(conn, album_id)
    if song is None:
        return None
    folder = str(PurePosixPath(song).parent)
    for name in COVER_FILES:
        found = _file(store, name if folder == "." else f"{folder}/{name}")
        if found is not None:
            return found
    return embedded(store, song)


def artist_cover(conn: Connection, store: LibraryStore, artist_id: str) -> Image | None:
    row = conn.execute("SELECT image_path FROM artists WHERE id = ?", (artist_id,)).fetchone()
    if row is None:
        return None
    found = _file(store, _opt_str(row["image_path"]))
    if found is not None:
        return found
    albums = conn.execute(
        "SELECT al.id FROM albums al WHERE al.artist_id = ? AND EXISTS"
        " (SELECT 1 FROM tracks t WHERE t.album_id = al.id AND t.status = 'ready')"
        " ORDER BY COALESCE(al.year, 0) DESC, al.id LIMIT 3",
        (artist_id,),
    ).fetchall()
    for album in albums:
        found = album_cover(conn, store, str(album["id"]))
        if found is not None:
            return found
    return None


def playlist_cover(
    conn: Connection, store: LibraryStore, playlist_id: str, user_id: str
) -> Image | None:
    visible = conn.execute(
        "SELECT 1 FROM playlists WHERE id = ? AND (owner_id = ? OR is_public = 1)",
        (playlist_id, user_id),
    ).fetchone()
    if visible is None:
        return None
    albums = conn.execute(
        "SELECT t.album_id FROM playlist_tracks p JOIN tracks t ON t.id = p.track_id"
        " WHERE p.playlist_id = ? AND t.status = 'ready' AND t.album_id IS NOT NULL"
        " ORDER BY p.position LIMIT 5",
        (playlist_id,),
    ).fetchall()
    for album in dict.fromkeys(str(a["album_id"]) for a in albums):
        found = album_cover(conn, store, album)
        if found is not None:
            return found
    return None


def _song_cover(conn: Connection, store: LibraryStore, video: str) -> tuple[Image | None, str]:
    """The album cover of an archived video, else the thumbnail URL the track row keeps."""
    ref = tracks_for_videos(conn, [video]).get(video)
    if ref is None:
        return None, ""
    row = conn.execute(
        "SELECT album_id, yt_thumbnail_url FROM tracks WHERE id = ?", (ref.id,)
    ).fetchone()
    if row is None:
        return None, ""
    if ref.status == "ready" and row["album_id"] is not None:
        found = album_cover(conn, store, str(row["album_id"]))
        if found is not None:
            return found, ""
    return None, str(row["yt_thumbnail_url"] or "")


# ---------------------------------------------------------------------- external


def check_url(url: str) -> str:
    """The thumbnail URL if it may be fetched (HTTPS, exact approved host), else error 70."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise not_found() from None
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or host not in ALLOWED_HOSTS
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
    ):
        raise not_found()
    return url


async def fetch(url: str, timeout_s: float) -> tuple[bytes, str]:
    """GETs an approved thumbnail: no redirects, `image/*`, at most `MAX_EXTERNAL_BYTES`."""
    check_url(url)
    try:
        async with (
            httpx.AsyncClient(follow_redirects=False, timeout=timeout_s, trust_env=False) as client,
            client.stream("GET", url, headers={"Accept": "image/*"}) as response,
        ):
            if response.status_code != 200:  # noqa: PLR2004
                raise not_found()
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            content_type = content_type.lower()
            if not content_type.startswith("image/"):
                raise not_found()
            declared = response.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > MAX_EXTERNAL_BYTES:
                raise not_found()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_EXTERNAL_BYTES:
                    raise not_found()
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable("Cover art host unavailable") from exc
    return bytes(body), content_type


class CoverCache:
    """Fetched thumbnails on disk: one file per virtual id (`<sha256>.<image subtype>`), its
    modification time set to the fetch time from the injected clock. Entries older than the
    TTL are ignored and replaced; past the size cap the oldest files are deleted."""

    def __init__(self, directory: Path, clock: Clock, *, ttl_s: int, max_bytes: int) -> None:
        self.directory = directory
        self._clock = clock
        self._ttl_s = ttl_s
        self._max_bytes = max_bytes

    def _stem(self, key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _entries(self, key: str) -> list[Path]:
        if not self.directory.is_dir():
            return []
        stem = self._stem(key)
        return [p for p in self.directory.iterdir() if p.name.startswith(stem + ".")]

    def get(self, key: str) -> tuple[bytes, str] | None:
        now = self._clock.now().timestamp()
        for path in self._entries(key):
            try:
                if now - path.stat().st_mtime > self._ttl_s:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            subtype = path.name.split(".", 1)[1]
            return data, f"image/{subtype}"
        return None

    def put(self, key: str, data: bytes, content_type: str) -> None:
        subtype = content_type.split("/", 1)[1] if "/" in content_type else ""
        if not _SUBTYPE.match(subtype):
            subtype = "jpeg"
        self.directory.mkdir(parents=True, exist_ok=True)
        for old in self._entries(key):
            old.unlink(missing_ok=True)
        target = self.directory / f"{self._stem(key)}.{subtype}"
        tmp = self.directory / f".{target.name}.{secrets.token_hex(4)}.tmp"
        tmp.write_bytes(data)
        moment = self._clock.now().timestamp()
        os.utime(tmp, (moment, moment))
        tmp.replace(target)
        self._evict()

    def _evict(self) -> None:
        files: list[tuple[float, int, Path]] = []
        for path in self.directory.iterdir():
            if path.name.startswith("."):
                continue
            with contextlib.suppress(OSError):
                stat = path.stat()
                files.append((stat.st_mtime, stat.st_size, path))
        total = sum(size for _, size, _ in files)
        for _, size, path in sorted(files, key=lambda f: (f[0], f[2].name)):
            if total <= self._max_bytes:
                break
            path.unlink(missing_ok=True)
            total -= size


# ---------------------------------------------------------------------- lookup


class Covers:
    def __init__(self, services: "Services", settings: LibrarySettings) -> None:
        self._services = services
        self._settings = settings
        self.cache = CoverCache(
            services.settings.data_dir / "covers",
            services.clock,
            ttl_s=settings.cover_cache_ttl_s,
            max_bytes=settings.cover_cache_max_bytes,
        )

    def _library(self, cover: CoverId, user_id: str) -> tuple[Image | None, str]:
        store = self._services.library
        with self._services.db.read() as conn:
            if cover.kind == "album":
                return album_cover(conn, store, cover.value), ""
            if cover.kind == "artist":
                return artist_cover(conn, store, cover.value), ""
            if cover.kind == "playlist":
                return playlist_cover(conn, store, cover.value, user_id), ""
            if cover.kind == "song":
                return _song_cover(conn, store, cover.value)
        return None, ""

    async def _thumbnail_url(self, cover: CoverId) -> str:
        catalog = self._services.catalog
        thumb = None
        if cover.kind == "song":
            thumb = (await catalog.track(cover.value)).thumbnail
        elif cover.kind == "external_album":
            thumb = (await catalog.album(cover.value)).ref.thumbnail
        else:
            thumb = (await catalog.artist(cover.value)).ref.thumbnail
        if thumb is None:
            raise not_found()
        return thumb.url

    async def image(self, raw_id: str, user_id: str) -> Image:
        cover = parse_cover_id(raw_id)
        found, url = await run_in_threadpool(self._library, cover, user_id)
        if found is not None:
            return found
        if cover.kind in ("album", "artist", "playlist"):
            raise not_found()
        key = raw_id
        cached = await run_in_threadpool(self.cache.get, key)
        if cached is not None:
            return Image(cached[1], data=cached[0])
        url = url or await self._thumbnail_url(cover)
        data, content_type = await fetch(url, self._settings.cover_fetch_timeout_s)
        await run_in_threadpool(self.cache.put, key, data, content_type)
        return Image(content_type, data=data)
