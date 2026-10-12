# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Matching a source track to a YouTube Music song: scores and hard rules."""

import pytest

from ultimatetunes.imports.files import SourceItem
from ultimatetunes.imports.matching import (
    THRESHOLD,
    album_score,
    artist_score,
    best_match,
    core_title,
    query_for,
    score,
)
from ultimatetunes.search.catalog import AlbumRef, ArtistRef, CatalogTrack


def song(  # noqa: PLR0913 - the fields a test sets
    *,
    title: str = "Night Ferry",
    artist: str = "The Paper Lanterns",
    album: str | None = "Lanterns at Dusk",
    duration: int | None = 241,
    video: str = "Wq5Jd7HsKe2",
    kind: str | None = "ATV",
) -> CatalogTrack:
    return CatalogTrack(
        video_id=video,
        title=title,
        artists=(ArtistRef(artist, None),),
        album=AlbumRef(album, None) if album else None,
        duration_s=duration,
        video_type=kind,  # type: ignore[arg-type]
    )


SOURCE = SourceItem("Night Ferry", ("The Paper Lanterns",), "Lanterns at Dusk", 240)


@pytest.mark.parametrize(
    ("title", "core"),
    [
        ("Night Ferry (feat. Marisol Vega)", "Night Ferry"),
        ("Night Ferry [Remastered 2011]", "Night Ferry"),
        ("Night Ferry - Radio Edit", "Night Ferry"),
        ("Night Ferry ft. Marisol Vega", "Night Ferry"),
        ("(Intro)", "(Intro)"),
    ],
)
def test_core_title(title: str, core: str) -> None:
    assert core_title(title) == core


def test_query() -> None:
    assert query_for(SOURCE) == "The Paper Lanterns Night Ferry"
    assert query_for(SourceItem("Song (Live)"), core=True) == "Song"


def test_a_perfect_match_scores_one() -> None:
    assert score(SOURCE, song()) == 1.0
    assert score(SOURCE, song(kind="OMV")) == 0.98


def test_hard_rules() -> None:
    assert score(SOURCE, song(title="Completely Different")) is None
    assert score(SOURCE, song(artist="Someone Else")) is None
    assert score(SOURCE, song(duration=244)) is None
    assert score(SOURCE, song(duration=243)) is not None
    assert score(SourceItem("!!!"), song(title="???")) is None


def test_neutral_fields() -> None:
    bare = SourceItem("Night Ferry")
    value = score(bare, song(album=None, duration=None))
    assert value == round(0.98 * (0.45 + 0.15 + 0.075 + 0.05) + 0.02, 4)
    assert value >= THRESHOLD


def test_partial_scores() -> None:
    assert artist_score(("Paper Lanterns",), ("The Paper Lanterns",)) == pytest.approx(2 / 3)
    assert artist_score(("A",), ("",)) == 0.0
    assert album_score("Lanterns", "Lanterns at Dusk") == 0.8
    assert album_score("Other", "Lanterns at Dusk") == 0.0
    assert album_score("x", None) == 0.5


def test_best_match_keeps_the_best_above_the_threshold() -> None:
    video = song(title="Night Ferry (Official Video)", album=None, kind="OMV", video="aaaaaaaaaaa")
    album = song(video="bbbbbbbbbbb")
    found = best_match(SOURCE, [video, album, song(title="Other", video="ccccccccccc")])
    assert found is not None
    assert found.track.video_id == "bbbbbbbbbbb"
    weak = SourceItem("Night Ferry", ("Lanterns Paper Orchestra Big Band",), "Other Album")
    assert best_match(weak, [song(duration=None)]) is None
    assert best_match(SOURCE, []) is None
