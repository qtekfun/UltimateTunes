# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Strong and weak MusicBrainz matches, release choice and defensive parsing."""

from typing import Any

import pytest

from ultimatetunes.tagging.matching import (
    Candidate,
    Query,
    YoutubeIds,
    best_candidate,
    best_release,
    credit_name,
    duration_agreement,
    from_musicbrainz,
    from_youtube,
    normalize,
    score,
    similarity,
)
from ultimatetunes.tagging.model import MusicBrainzIds

QUERY = Query("Paper Moons (Live)", "The Paper Lanterns", "Lanterns at Dusk", 262000)
HINTS = YoutubeIds("MPREb_k3Vd9QmT2xL", "UCq8XbV1r0LwZ5mN3tYp7kQe", 4, 2024)


def test_normalize_and_similarity() -> None:
    assert normalize("  Björk — HOMOGENIC!! ") == "björk homogenic"
    assert similarity("Paper Moons", "paper moons") == 1.0
    assert similarity("Paper Moons (Live)", "Paper Moons [Live at Dusk]") == 1.0
    assert similarity("", "x") == 0.0
    assert similarity("abc", "xyz") < 0.5


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [(None, 1, 0.5), (1000, None, 0.5), (1000, 2900, 1.0), (1000, 7000, 0.5), (0, 20000, 0.0)],
)
def test_duration_agreement(left: int | None, right: int | None, expected: float) -> None:
    assert duration_agreement(left, right) == expected


def test_the_fixture_has_a_strong_and_a_weak_candidate(mb_search: dict[str, Any]) -> None:
    recordings = mb_search["recordings"]
    best = best_candidate(QUERY, recordings)
    assert best is not None
    assert best.recording["id"] == "2b4d6f8a-1c3e-4a5b-9d7f-0e2c4a6b8d01"
    assert best.score > 0.95
    assert score(QUERY, recordings[1]) < 0.85
    assert best_candidate(QUERY, []) is None
    assert best_candidate(QUERY, "nope") is None  # type: ignore[arg-type]


def test_a_strong_match_takes_musicbrainz_data(mb_search: dict[str, Any]) -> None:
    candidate = Candidate(0.97, mb_search["recordings"][0])
    meta = from_musicbrainz(QUERY, HINTS, candidate)
    assert (meta.title, meta.artist, meta.album_artist) == (
        "Paper Moons (Live)",
        "The Paper Lanterns",
        "The Paper Lanterns",
    )
    assert meta.artist_sort == "Paper Lanterns, The"
    assert meta.album == "Lanterns at Dusk"  # the release closest to the YouTube album
    assert (meta.track_number, meta.disc_number, meta.total_tracks, meta.total_discs) == (
        4,
        1,
        9,
        None,
    )
    assert (meta.year, meta.genre, meta.release_type, meta.isrc) == (
        2024,
        "Indie Pop",
        "live",
        "XXA012400004",
    )
    assert meta.musicbrainz == MusicBrainzIds(
        recording_id="2b4d6f8a-1c3e-4a5b-9d7f-0e2c4a6b8d01",
        track_id="3e4f5a6b-7c8d-4e9f-8a0b-1c2d3e4f5a07",
        release_id="4d6f8a0c-3e5a-4b7c-8f9a-1b3d5f7a9c02",
        release_group_id="7c8d9e0f-1a2b-4c3d-9e4f-5a6b7c8d9e04",
        artist_id="5f0c2d6e-8b1a-4c3d-9e7f-1a2b3c4d5e01",
        album_artist_id="5f0c2d6e-8b1a-4c3d-9e7f-1a2b3c4d5e01",
    )
    assert (meta.album_browse_id, meta.artist_channel_id) == (
        HINTS.album_browse_id,
        HINTS.artist_channel_id,
    )
    assert (meta.needs_review, meta.match_score) == (False, 0.97)


def test_without_a_youtube_album_the_official_earliest_release_wins(
    mb_search: dict[str, Any],
) -> None:
    query = Query("Paper Moons (Live)", "The Paper Lanterns", None, 262000)
    release = best_release(query, mb_search["recordings"][0])
    assert release is not None
    assert release["title"] == "Lanterns at Dusk"
    assert release["status"] == "Official"
    assert best_release(query, {"releases": []}) is None


def test_several_artists_and_a_bare_recording(mb_search: dict[str, Any]) -> None:
    recording = mb_search["recordings"][1]
    assert credit_name(recording["artist-credit"]) == "Another Band & The Paper Lanterns"
    assert credit_name([{"joinphrase": "x"}]) is None
    assert credit_name([{"artist": {"name": "Solo"}}]) == "Solo"
    assert credit_name("nope") is None
    meta = from_musicbrainz(QUERY, YoutubeIds(year=1999), Candidate(0.9, recording))
    assert meta.artist == "Another Band & The Paper Lanterns"
    assert meta.artist_sort is None  # only for a single artist
    assert meta.album == "Lanterns at Dusk"  # no release: the YouTube album
    assert (meta.track_number, meta.year, meta.genre, meta.release_type) == (
        None,
        1999,
        None,
        None,
    )
    assert meta.musicbrainz.artist_id is None  # "not-a-uuid" is dropped


def test_odd_values_are_dropped() -> None:
    recording: dict[str, Any] = {
        "id": "../../etc",
        "title": " \x00 ",
        "length": "262000",
        "artist-credit": [{"name": "X", "artist": "not a dict"}],
        "isrcs": ["xxa012400004", 7],
        "tags": [{"count": 2, "name": " "}],
        "first-release-date": "unknown",
        "releases": [
            {
                "title": 42,
                "date": None,
                "release-group": {"primary-type": "Single", "secondary-types": [7]},
                "media": [{"position": True, "track-count": "12", "track": [{"position": 3}]}],
            }
        ],
    }
    meta = from_musicbrainz(Query("T", "X", None, None), YoutubeIds(), Candidate(0.9, recording))
    assert (meta.title, meta.album, meta.track_number, meta.disc_number) == ("T", "T", 3, None)
    assert (meta.total_tracks, meta.release_type, meta.genre, meta.isrc) == (
        12,
        "single",
        None,
        None,
    )
    assert meta.musicbrainz == MusicBrainzIds()
    assert meta.year is None
    recording["releases"][0]["release-group"] = {"secondary-types": []}
    meta = from_musicbrainz(Query("T", "X", None, None), YoutubeIds(), Candidate(0.9, recording))
    assert meta.release_type is None


def test_a_weak_match_keeps_youtube_data() -> None:
    meta = from_youtube(QUERY, HINTS, match_score=0.4)
    assert (meta.title, meta.artist, meta.album_artist, meta.album) == (
        "Paper Moons (Live)",
        "The Paper Lanterns",
        "The Paper Lanterns",
        "Lanterns at Dusk",
    )
    assert (meta.track_number, meta.year, meta.needs_review, meta.match_score) == (
        4,
        2024,
        True,
        0.4,
    )
    single = from_youtube(Query("Solo Song", "A", None, None), YoutubeIds(), match_score=None)
    assert single.album == "Solo Song"
