# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendering of items with missing fields (the end-to-end shapes are in test_routes)."""

from dataclasses import replace

from ultimatetunes.search import render
from ultimatetunes.search.catalog import ArtistRef, CatalogAlbumRef, CatalogTrack
from ultimatetunes.search.library import LibrarySong
from ultimatetunes.search.service import ExternalSong

SONG = LibrarySong(
    id="0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001",
    title="Lighthouse Keeper",
    artist_name="The Paper Lanterns",
    album_name=None,
    album_id=None,
    artist_id="0199d6a2-4c1e-7b3a-9f10-2a6c8e01a001",
    track_number=None,
    disc_number=None,
    year=None,
    genre=None,
    duration_ms=None,
    path="x.opus",
    format="opus",
    content_type="audio/ogg",
    size_bytes=10,
    bit_rate_kbps=None,
    sample_rate_hz=None,
    channels=None,
    rg_track_gain_db=None,
    rg_track_peak=None,
    rg_album_gain_db=None,
    rg_album_peak=None,
    musicbrainz_recording_id=None,
    created_at="2026-10-01T10:00:00.000Z",
    album_artist_id=None,
    album_artist_name=None,
    starred_at=None,
    play_count=None,
    last_played_at=None,
)


def test_library_song_without_album() -> None:
    child = render.library_child(SONG)
    assert "coverArt" not in child
    assert "parent" not in child
    assert child["albumArtists"] == child["artists"]
    assert child["displayAlbumArtist"] == "The Paper Lanterns"
    assert child["replayGain"] == {}
    assert child["musicBrainzId"] == ""
    assert render.track_item(SONG)["coverArt"] == f"ar-{SONG.artist_id}"
    orphan = replace(SONG, artist_id=None)
    assert render.track_item(orphan)["coverArt"] == ""
    assert render.library_child(orphan)["artists"] == []


def test_external_items_without_ids() -> None:
    bare = ExternalSong(CatalogTrack("Up1Lo2Ad3Zz", "Fan upload", (ArtistRef("Uploader"),)))
    child = render.child(bare)
    assert child["artists"] == []
    assert child["displayArtist"] == "Uploader"
    assert "artistId" not in child
    assert "albumId" not in child
    item = render.track_item(bare)
    assert (item["artistId"], item["album"], item["albumId"]) == (None, None, None)
    nameless = render.album_id3(CatalogAlbumRef("MPREb_x", "Untitled", ()), "now")
    assert "artist" not in nameless
    assert nameless["displayArtist"] == ""
