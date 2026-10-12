# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Imports on the wire (contracts/openapi/ut-v1.yaml: `ImportSummary`, `Import`, `ImportItem`).

A matched item's `track` is the library track behind it: archived (`ready`) it shows with its
library ids; still pending or failed it shows as the external `yt:` song with that state, like
the contract example. `progress` is the share of items that are no longer `pending` (1 once the
import is `done`).
"""

from collections.abc import Mapping, Sequence

from ultimatetunes.ids.virtual import album_id, artist_id, song_id
from ultimatetunes.imports.repository import ImportRow, ItemRow, TrackRow

type Obj = dict[str, object]


def _seconds(ms: int | None) -> int | None:
    return None if ms is None else round(ms / 1000)


def progress(row: ImportRow) -> float:
    if row.state == "done":
        return 1.0
    if row.total_items <= 0:
        return 0.0
    return round(min(1.0, row.done_items / row.total_items), 4)


def summary(row: ImportRow) -> Obj:
    error = (
        {"code": row.error_code, "message": row.error_message or row.error_code}
        if row.state == "failed" and row.error_code
        else None
    )
    return {
        "id": row.id,
        "source": row.source,
        "sourceUrl": row.source_url,
        "name": row.name,
        "createdAt": row.created_at,
        "state": row.state,
        "total": row.total_items,
        "matched": row.matched_items,
        "notFound": row.not_found_items,
        "progress": progress(row),
        "playlistId": row.playlist_id,
        "error": error,
        "updatedAt": row.updated_at,
        "finishedAt": row.finished_at,
    }


def _library_cover(track: TrackRow) -> str:
    if track.album_id:
        return f"al-{track.album_id}"
    return f"ar-{track.artist_id}" if track.artist_id else ""


def track_item(track: TrackRow) -> Obj:
    if track.status == "ready" or track.yt_video_id is None:
        return {
            "id": track.id,
            "title": track.title,
            "artist": track.artist_name,
            "artistId": track.artist_id,
            "album": track.album_name,
            "albumId": track.album_id,
            "durationSec": _seconds(track.duration_ms),
            "year": track.year,
            "coverArt": _library_cover(track),
            "isExternal": track.status != "ready",
            "libraryState": track.status,
        }
    return {
        "id": song_id(track.yt_video_id),
        "title": track.title,
        "artist": track.artist_name,
        "artistId": artist_id(track.yt_artist_channel_id) if track.yt_artist_channel_id else None,
        "album": track.album_name,
        "albumId": album_id(track.yt_album_browse_id) if track.yt_album_browse_id else None,
        "durationSec": _seconds(track.duration_ms),
        "year": track.year,
        "coverArt": song_id(track.yt_video_id),
        "isExternal": True,
        "libraryState": track.status,
    }


def item(row: ItemRow, tracks: Mapping[str, TrackRow]) -> Obj:
    track = tracks.get(row.track_id) if row.track_id else None
    return {
        "position": row.position,
        "sourceTitle": row.source_title,
        "sourceArtist": row.source_artist,
        "sourceAlbum": row.source_album,
        "sourceDurationSec": _seconds(row.source_duration_ms),
        "state": row.state,
        "matchScore": row.match_score,
        "track": track_item(track) if track is not None else None,
        "error": row.error_message,
    }


def full(row: ImportRow, items: Sequence[ItemRow], tracks: Mapping[str, TrackRow]) -> Obj:
    return {**summary(row), "items": [item(i, tracks) for i in items]}
