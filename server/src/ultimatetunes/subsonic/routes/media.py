# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: binary endpoints: cover art, stream and download. Owner: PLAN T05 (library
files); songs without an archived file go through the `PendingStreams` seam (`library.stream`)
that streaming while downloading (PLAN T16) installs.

- `stream` / `download`: never transcoded. A library song (also a `yt:` id or a merged id that
  resolves to one) is its file with HTTP Range: `200` + `Accept-Ranges`, `206`, `416`. A song
  whose download failed answers error 70 with HTTP 404 (`StreamFailed`). A `yt:` id without a
  library track, or a `pending` track, is handed to `app.state.pending_streams` (a `HEAD` is
  flagged so it never starts a download). `download` adds `Content-Disposition: attachment`.
- `getCoverArt`: `library.covers` (library images from `/music`, thumbnails of virtual ids
  from the approved YouTube image hosts through a disk cache). `size` is ignored (v1).

All three answer `HEAD` (`head=True`): same status and headers, no body.
"""

from dataclasses import dataclass
from pathlib import PurePosixPath

from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from ultimatetunes.errors import NotFound, PathRejected, StreamFailed
from ultimatetunes.ids.resolve import TrackRef, resolve_track
from ultimatetunes.ids.virtual import VirtualId, parse_kind
from ultimatetunes.library.covers import Covers
from ultimatetunes.library.stream import CONTENT_TYPES, PendingStreams, attachment, file_response
from ultimatetunes.library.web import library_settings
from ultimatetunes.subsonic.router import SubsonicRequest, SubsonicRouter

router = SubsonicRouter()

COVER_CACHE_CONTROL = "private, max-age=86400"


@dataclass(frozen=True)
class LibraryFile:
    path: str
    content_type: str


@dataclass(frozen=True)
class Pending:
    target: TrackRef | VirtualId
    video: str | None


def _locate(req: SubsonicRequest, raw: str) -> LibraryFile | Pending:
    with req.services.db.read() as conn:
        target = resolve_track(conn, raw)
        if isinstance(target, VirtualId):
            return Pending(target, target.payload)
        row = conn.execute(
            "SELECT path, format, content_type, yt_video_id FROM tracks WHERE id = ?",
            (target.id,),
        ).fetchone()
    if row is None:  # removed between the two reads
        raise NotFound("Song not found")
    if target.status == "failed":
        raise StreamFailed()
    if target.status == "pending" or row["path"] is None:
        video = row["yt_video_id"]
        return Pending(target, None if video is None else str(video))
    fmt = str(row["format"] or "")
    content_type = str(row["content_type"] or CONTENT_TYPES.get(fmt, "application/octet-stream"))
    return LibraryFile(str(row["path"]), content_type)


async def _serve(req: SubsonicRequest, *, download: bool) -> Response:
    raw = req.require("id")
    parse_kind(raw, "song")
    found = await run_in_threadpool(_locate, req, raw)
    head = req.request.method == "HEAD"
    if isinstance(found, Pending):
        streams: PendingStreams = req.request.app.state.pending_streams
        return await streams.serve(
            req, found.target, video=found.video, download=download, head=head
        )
    store = req.services.library
    try:
        size = await run_in_threadpool(store.size, found.path)
    except (OSError, PathRejected):
        raise NotFound("Song file is missing") from None
    extra = {"Content-Disposition": attachment(PurePosixPath(found.path).name)} if download else {}
    return file_response(
        store,
        found.path,
        size=size,
        content_type=found.content_type,
        range_header=req.request.headers.get("range"),
        extra_headers=extra,
    )


@router.endpoint("getCoverArt", head=True)
async def get_cover_art(req: SubsonicRequest) -> Response:
    raw = req.require("id")
    image = await Covers(req.services, library_settings()).image(raw, req.user.user_id)
    headers = {"Cache-Control": COVER_CACHE_CONTROL, "X-Content-Type-Options": "nosniff"}
    if image.data is not None:
        return Response(image.data, media_type=image.content_type, headers=headers)
    return file_response(
        req.services.library,
        str(image.path),
        size=image.size,
        content_type=image.content_type,
        range_header=None,
        extra_headers=headers,
    )


@router.endpoint("stream", head=True)
async def stream(req: SubsonicRequest) -> Response:
    return await _serve(req, download=False)


@router.endpoint("download", head=True)
async def download(req: SubsonicRequest) -> Response:
    return await _serve(req, download=True)
