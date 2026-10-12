# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Records of the archive step and their wire form (contracts/openapi/internal-worker.yaml:
`TrackMetadata`, `ReplayGainValues`, `FileInfo`)."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ArchiveKind:
    """An archive format (SPEC section 11): never transcoded, only remuxed."""

    format: str
    ext: str
    content_type: str
    muxer: str
    muxer_args: tuple[str, ...] = ()


OPUS = ArchiveKind("opus", "opus", "audio/ogg", "ogg")
M4A = ArchiveKind("m4a", "m4a", "audio/mp4", "mp4", ("-movflags", "+faststart"))
# Audio codec (ffprobe `codec_name`) -> archive kind. Anything else is refused.
KIND_BY_CODEC = {"opus": OPUS, "aac": M4A}
KIND_BY_EXT = {OPUS.ext: OPUS, M4A.ext: M4A}


@dataclass(frozen=True)
class ReplayGain:
    """ReplayGain 2.0 values (reference -18 LUFS); peaks are linear (1.0 = full scale)."""

    track_gain_db: float
    track_peak: float
    album_gain_db: float | None = None
    album_peak: float | None = None

    def to_contract(self) -> dict[str, Any]:
        return {
            "trackGainDb": self.track_gain_db,
            "trackPeak": self.track_peak,
            "albumGainDb": self.album_gain_db,
            "albumPeak": self.album_peak,
        }


@dataclass(frozen=True)
class MusicBrainzIds:
    recording_id: str | None = None
    track_id: str | None = None
    release_id: str | None = None
    release_group_id: str | None = None
    artist_id: str | None = None
    album_artist_id: str | None = None

    def to_contract(self) -> dict[str, Any]:
        return {
            "recordingId": self.recording_id,
            "trackId": self.track_id,
            "releaseId": self.release_id,
            "releaseGroupId": self.release_group_id,
            "artistId": self.artist_id,
            "albumArtistId": self.album_artist_id,
        }


@dataclass(frozen=True)
class TrackMetadata:
    """The tags written to the file and sent to `registerTrack` (RF-04)."""

    title: str
    artist: str
    album_artist: str
    album: str
    artist_sort: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    total_tracks: int | None = None
    total_discs: int | None = None
    year: int | None = None
    genre: str | None = None
    release_type: str | None = None
    isrc: str | None = None
    musicbrainz: MusicBrainzIds = field(default_factory=MusicBrainzIds)
    album_browse_id: str | None = None
    artist_channel_id: str | None = None
    needs_review: bool = True
    match_score: float | None = None

    def to_contract(self, replay_gain: ReplayGain, cover_path: str | None) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "artistSort": self.artist_sort,
            "albumArtist": self.album_artist,
            "album": self.album,
            "trackNumber": self.track_number,
            "discNumber": self.disc_number,
            "totalTracks": self.total_tracks,
            "totalDiscs": self.total_discs,
            "year": self.year,
            "genre": self.genre,
            "releaseType": self.release_type,
            "isrc": self.isrc,
            "musicbrainz": self.musicbrainz.to_contract(),
            "youtube": {
                "albumBrowseId": self.album_browse_id,
                "artistChannelId": self.artist_channel_id,
            },
            "replayGain": replay_gain.to_contract(),
            "needsReview": self.needs_review,
            "matchScore": self.match_score,
            "coverPath": cover_path,
        }


@dataclass(frozen=True)
class FileInfo:
    """The archive file as registered (`FileInfo`)."""

    kind: ArchiveKind
    size_bytes: int
    duration_ms: int
    sha256: str
    bit_rate_kbps: int | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None

    def to_contract(self) -> dict[str, Any]:
        return {
            "format": self.kind.format,
            "contentType": self.kind.content_type,
            "sizeBytes": self.size_bytes,
            "durationMs": self.duration_ms,
            "bitRateKbps": self.bit_rate_kbps,
            "sampleRateHz": self.sample_rate_hz,
            "channels": self.channels,
            "sha256": self.sha256,
        }
