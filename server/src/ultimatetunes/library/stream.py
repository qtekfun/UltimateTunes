# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Serving library files with HTTP Range (`stream`, `download`, library covers).

`file_response` answers `200` with the exact `Content-Length` and `Accept-Ranges: bytes`; a
single satisfiable `Range` gets `206` with `Content-Range`, a range starting past the end gets
`416` with `Content-Range: bytes */<size>` (contracts/errors.md). Several ranges or a
malformed header are ignored (RFC 9110 allows answering the whole file). The file is opened
through `LibraryStore` only when the body is sent, so `HEAD` never reads it.

Songs that are not archived yet (`yt:` ids in flight, a `pending` track) are not served
here: `PendingStreams` is the seam where streaming while downloading (PLAN T16) plugs in.
Until it does, they answer `FeatureNotImplemented`. A `HEAD` must never start a download.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote

from starlette.responses import Response, StreamingResponse

from ultimatetunes.core.storage import LibraryStore
from ultimatetunes.errors import FeatureNotImplemented
from ultimatetunes.ids.resolve import TrackRef
from ultimatetunes.ids.virtual import VirtualId

if TYPE_CHECKING:
    from ultimatetunes.subsonic.router import SubsonicRequest

CHUNK = 64 * 1024
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")

CONTENT_TYPES = {
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
}


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int  # inclusive

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class RangeNotSatisfiableError(Exception):
    """The range starts past the end of the file (416)."""


def parse_range(header: str | None, size: int) -> ByteRange | None:
    """The single byte range of `header` within `size` bytes; None means the whole file."""
    if not header:
        return None
    match = _RANGE.match(header.strip())
    if match is None:
        return None
    first, last = match.group(1), match.group(2)
    if not first and not last:
        return None
    if not first:
        suffix = int(last)
        if suffix == 0 or size == 0:
            raise RangeNotSatisfiableError
        return ByteRange(max(0, size - suffix), size - 1)
    start = int(first)
    if last and int(last) < start:
        return None
    if start >= size:
        raise RangeNotSatisfiableError
    end = int(last) if last else size - 1
    return ByteRange(start, min(end, size - 1))


def _read(store: LibraryStore, path: str, start: int, length: int) -> Iterator[bytes]:
    with store.open_read(path) as handle:
        handle.seek(start)
        left = length
        while left > 0:
            chunk = handle.read(min(CHUNK, left))
            if not chunk:
                return
            left -= len(chunk)
            yield chunk


def attachment(name: str) -> str:
    """`Content-Disposition` of a download (RFC 6266 with an RFC 5987 UTF-8 name)."""
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", name) or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"


def file_response(  # noqa: PLR0913 - what one file response needs
    store: LibraryStore,
    path: str,
    *,
    size: int,
    content_type: str,
    range_header: str | None,
    extra_headers: dict[str, str] | None = None,
) -> Response:
    headers = {"Accept-Ranges": "bytes", **(extra_headers or {})}
    try:
        byte_range = parse_range(range_header, size)
    except RangeNotSatisfiableError:
        headers["Content-Range"] = f"bytes */{size}"
        return Response(status_code=416, headers=headers)
    if byte_range is None:
        headers["Content-Length"] = str(size)
        body = _read(store, path, 0, size)
        return StreamingResponse(body, 200, headers=headers, media_type=content_type)
    headers["Content-Length"] = str(byte_range.length)
    headers["Content-Range"] = f"bytes {byte_range.start}-{byte_range.end}/{size}"
    body = _read(store, path, byte_range.start, byte_range.length)
    return StreamingResponse(body, 206, headers=headers, media_type=content_type)


class PendingStreams(Protocol):
    """Streams a song that has no archived file yet: a `yt:` id without a library track
    (`target` is the `VirtualId`) or a `pending` track (`target` is its `TrackRef`, `video`
    its video id). `head`: the request is a `HEAD`, which must not request any download."""

    async def serve(
        self,
        req: "SubsonicRequest",
        target: TrackRef | VirtualId,
        *,
        video: str | None,
        download: bool,
        head: bool,
    ) -> Response: ...


class NotStreamingYet:
    """The default until PLAN T16 installs streaming while downloading (`app.state`)."""

    async def serve(
        self,
        req: "SubsonicRequest",
        target: TrackRef | VirtualId,
        *,
        video: str | None,
        download: bool,
        head: bool,
    ) -> Response:
        raise FeatureNotImplemented("Streaming while downloading is not available yet")
