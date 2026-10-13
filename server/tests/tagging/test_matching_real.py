# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Matching against real (trimmed) MusicBrainz answers for tracks YouTube Music lists with
several artists or a "(feat. X)" title, and the false positives that must stay out."""

import json
from typing import Any

import pytest

from ultimatetunes.tagging.matching import (
    Query,
    artist_names,
    artist_similarity,
    best_candidate,
    score,
    split_featuring,
    title_similarity,
)
from ultimatetunes.tagging.musicbrainz import search_query

from .conftest import FIXTURES

MIN_SCORE = 0.85
REAL: dict[str, Any] = json.loads((FIXTURES / "musicbrainz_real.json").read_text())


def case(name: str) -> tuple[Query, list[dict[str, Any]]]:
    data = REAL[name]
    return Query(**data["query"]), data["recordings"]


@pytest.mark.parametrize(
    ("name", "recording_id"),
    [
        ("sin_verguenza", "506bb224-"),
        ("muerdeme", "228e932e-"),
        ("baja_por_diversion", "5dacac06-"),  # credited "La Fuga & El Drogas"
        ("bzrp_52", "ceb41ddc-"),
        ("mon_amour_remix", "954cc393-"),
    ],
)
def test_multi_artist_and_featured_tracks_match(name: str, recording_id: str) -> None:
    query, recordings = case(name)
    best = best_candidate(query, recordings)
    assert best is not None
    assert best.score >= MIN_SCORE
    assert best.recording["id"].startswith(recording_id)


@pytest.mark.parametrize(
    "name",
    [
        "gone_gone_gone",  # the only same-title studio recording is 12 s shorter
        "largate",  # the only recording is 17 s shorter
        "tu_enemigo",  # the version with Juanes is not in MusicBrainz
        "pero_a_tu_lado_live",  # the 2019 live take is not in MusicBrainz, only studio ones
    ],
)
def test_genuinely_weak_matches_stay_weak(name: str) -> None:
    query, recordings = case(name)
    best = best_candidate(query, recordings)
    assert best is not None
    assert best.score < MIN_SCORE


def test_different_songs_and_versions_by_the_same_artist_stay_out() -> None:
    query, recordings = case("bzrp_52")
    other_sessions = [rec for rec in recordings if not rec["id"].startswith("ceb41ddc-")]
    assert max(score(query, rec) for rec in other_sessions) < 0.75
    query, recordings = case("mon_amour_remix")
    originals = [rec for rec in recordings if "remix" not in rec["title"].lower()]
    assert max(score(query, rec) for rec in originals) < MIN_SCORE
    query, recordings = case("tu_enemigo")
    live = next(rec for rec in recordings if "live" in rec.get("disambiguation", ""))
    assert score(query, live) < 0.75


def test_a_cover_by_another_artist_stays_out() -> None:
    query, recordings = case("sin_verguenza")
    cover = dict(recordings[0], **{"artist-credit": [{"name": "Los Imitadores"}]})
    assert score(query, cover) < 0.75
    query, recordings = case("muerdeme")
    cover = dict(recordings[0], **{"artist-credit": [{"name": "Suu"}]})
    assert score(query, cover) < MIN_SCORE


def test_the_query_asks_for_the_primary_artist_and_the_bare_title() -> None:
    query, _ = case("baja_por_diversion")
    assert search_query(query) == (
        '(recording:"Baja por diversión" AND artist:"La Fuga") OR '
        '(recording:"Baja por diversión" AND artist:"La Fuga" AND release:"Negociando gasolina")'
    )
    query, _ = case("pero_a_tu_lado_live")
    assert search_query(query, loose=True) == (
        "recording:(pero a tu lado en directo wizink center madrid 17 11 2019)"
        ' AND artist:"Los Secretos"'
    )
    assert search_query(Query("!!", "", None, None), loose=True) == 'recording:"!!" AND artist:""'


@pytest.mark.parametrize(
    ("title", "bare", "featured"),
    [
        ("Tu Enemigo (feat. Juanes)", "Tu Enemigo", ["Juanes"]),
        ("Song [ft. A & B]", "Song", ["A", "B"]),
        ("Song feat. A", "Song", ["A"]),
        ("Song feat. A (Live)", "Song (Live)", ["A"]),
        ("Song ft. A & B [Remix] (Live)", "Song [Remix] (Live)", ["A", "B"]),
        ("To Sir (With Love)", "To Sir (With Love)", []),
        ("Song Featuring A, B", "Song", ["A", "B"]),
        ("Feather (Remix)", "Feather (Remix)", []),
        ("Without You", "Without You", []),
    ],
)
def test_featured_parts_are_split_off(title: str, bare: str, featured: list[str]) -> None:
    assert split_featuring(title) == (bare, featured)


def test_artist_names() -> None:
    assert artist_names("David Guetta, Teddy Swims, Tones And I") == [
        "David Guetta",
        "Teddy Swims",
        "Tones And I",
    ]
    assert artist_names("Simon & Garfunkel") == ["Simon", "Garfunkel"]
    assert artist_names(" , ") == []


def test_artists_compare_as_sets_or_as_printed() -> None:
    query = Query("T", "zzoilo, Aitana", None, None)
    reordered = [{"name": "Aitana", "joinphrase": " & "}, {"name": "Zzoilo"}]
    assert artist_similarity(query, reordered) == 1.0
    duo = Query("T", "Simon & Garfunkel", None, None)
    assert artist_similarity(duo, [{"name": "Simon & Garfunkel"}]) == 1.0  # as printed
    assert artist_similarity(query, []) == 0.0
    assert artist_similarity(Query("T", "", None, None), [{"name": "A"}]) == 0.0
    featured = Query("T (feat. B)", "A", None, None)
    credit = [{"name": "A", "joinphrase": " feat. "}, {"name": "B"}]
    assert artist_similarity(featured, credit) == 1.0
    assert artist_similarity(featured, [{"name": "A"}]) < 0.8


def test_version_markers_keep_takes_apart() -> None:
    assert title_similarity("Paper Moons (Live)", "Paper Moons [En directo]") == 1.0
    assert title_similarity("Song (Acústico)", "Song (acoustic version)") == 1.0
    assert title_similarity("Song", "Song (Remix)") < 0.8
    assert title_similarity("Song", "Song", "live, 2015-11-12") < 0.9
    assert title_similarity("Song (feat. X)", "Song") == 1.0
    assert title_similarity("!!", "Song (Live)") == 0.0


def recording(title: str, artists: list[str], length: int, note: str = "") -> dict[str, Any]:
    credit = [{"name": name} for name in artists]
    return {"title": title, "artist-credit": credit, "length": length, "disambiguation": note}


@pytest.mark.parametrize(
    ("query", "candidate"),
    [
        (
            Query("Bohemian Rhapsody (Live)", "Queen", None, 354000),
            recording("Bohemian Rhapsody", ["Queen"], 354000),
        ),
        (
            Query("Bohemian Rhapsody", "Queen", None, 354000),
            recording("Bohemian Rhapsody", ["Queen"], 354000, "live, 1986"),
        ),
        (
            Query("Something Just Like This (Remix)", "The Chainsmokers, Coldplay", None, 247000),
            recording("Something Just Like This", ["The Chainsmokers", "Coldplay"], 247000),
        ),
        (
            Query("Something Just Like This", "The Chainsmokers, Coldplay", None, 247000),
            recording("Something Just Like This (Remix)", ["The Chainsmokers", "Coldplay"], 247000),
        ),
        (
            Query("Song feat. A (Live)", "B", None, 200000),
            recording("Song", ["B", "A"], 200000),
        ),
    ],
)
def test_another_version_of_a_long_title_never_reaches_the_threshold(
    query: Query, candidate: dict[str, Any]
) -> None:
    assert score(query, candidate) < MIN_SCORE


def test_a_solo_recording_never_stands_in_for_a_featured_version() -> None:
    query = Query("Song (feat. B)", "A", None, 200000)
    assert score(query, recording("Song", ["A"], 200000)) < MIN_SCORE
    assert score(query, recording("Song", ["A", "B"], 200000)) == 1.0
    query, recordings = case("tu_enemigo")
    solo = dict(recordings[2], length=query.duration_ms)  # same length as the YouTube track
    assert score(query, solo) < MIN_SCORE


def test_with_in_brackets_is_part_of_the_title() -> None:
    query = Query("To Sir (With Love)", "Lulu", None, 165000)
    assert score(query, recording("To Sir With Love", ["Lulu"], 165000)) == 1.0


def test_a_disambiguation_marker_counts_once_and_only_when_new() -> None:
    live_take = Query("Song (Live)", "A", None, 200000)
    assert score(live_take, recording("Song (live)", ["A"], 200000, "live, 2015")) == 1.0
    assert score(live_take, recording("Song", ["A"], 200000, "live, 2015")) == 1.0
    studio = Query("Live Forever", "Oasis", None, 276000)
    assert score(studio, recording("Live Forever", ["Oasis"], 276000, "live, 1995")) < MIN_SCORE
    assert score(studio, recording("Live Forever", ["Oasis"], 276000)) == 1.0
    live = Query("Live Forever (Live)", "Oasis", None, 276000)
    assert score(live, recording("Live Forever (live)", ["Oasis"], 276000, "live")) == 1.0
    assert score(live, recording("Live Forever - Live", ["Oasis"], 276000, "live")) == 1.0


def test_featured_artists_are_found_accents_aside_or_inside_the_printed_credit() -> None:
    query = Query("Song (feat. Suu)", "Despistaos", None, 200000)
    assert score(query, recording("Song", ["Despistaos", "Süu"], 200000)) >= MIN_SCORE
    by_artist_name = {
        "title": "Song",
        "length": 200000,
        "artist-credit": [
            {"name": "Despistaos", "joinphrase": " feat. "},
            {"name": "S.", "artist": {"name": "Süu"}},
        ],
    }
    assert artist_similarity(query, by_artist_name["artist-credit"]) > 0.5  # not capped
    duo = Query("Song (feat. Garfunkel)", "Paul Simon", None, 200000)
    assert score(duo, recording("Song", ["Paul Simon", "Simon & Garfunkel"], 200000)) >= MIN_SCORE
    assert score(duo, recording("Song", ["Paul Simon", "Simon & Garfunkelson"], 200000)) < (
        MIN_SCORE
    )


@pytest.mark.parametrize(
    ("query", "candidate"),
    [
        (Query("Song (Remastered 2011)", "A", None, 200000), recording("Song", ["A"], 200000)),
        (Query("Song (Radio Edit)", "A", None, 200000), recording("Song", ["A"], 200000)),
        (
            Query("Song (feat. B) [Radio Edit]", "A", None, 200000),
            recording("Song [Radio Edit]", ["A", "B"], 200000),
        ),
        (Query("Song (Original Mix)", "A", None, 200000), recording("Song", ["A"], 200000)),
        (Query("Song", "A", None, 200000), recording("Song (2011 remaster)", ["A"], 200000)),
    ],
)
def test_remasters_edits_and_original_mixes_still_match(
    query: Query, candidate: dict[str, Any]
) -> None:
    assert score(query, candidate) >= MIN_SCORE
