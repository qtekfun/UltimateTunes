# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""mutagen tags on the archive fixtures, compared with golden files (`fixtures/golden_*.json`).

Set `UT_UPDATE_GOLDEN=1` to rewrite the golden files after a deliberate change, and review
the diff."""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus

from tests.tagging.conftest import FIXTURES, copy_fixture, sample_metadata
from ultimatetunes.tagging import tags as tags_module
from ultimatetunes.tagging.model import M4A, OPUS, ArchiveKind, ReplayGain
from ultimatetunes.tagging.tags import (
    TaggingError,
    mp4_atoms,
    read_track_gain,
    vorbis_comments,
    write_replay_gain,
    write_tags,
)

GAIN = ReplayGain(-7.85, 0.993)
ALBUM = ReplayGain(-7.85, 0.993, -6.5, 0.998)
WEIRD = ArchiveKind("flac", "flac", "audio/flac", "flac")


def dump(path: Path) -> dict[str, Any]:
    """Every tag of the file as plain JSON (MP4 free-form values decoded)."""
    if path.suffix == ".opus":
        opus: Any = OggOpus(path)  # type: ignore[no-untyped-call]
        return {key.upper(): list(values) for key, values in sorted(opus.tags.as_dict().items())}
    mp4: Any = MP4(path)  # type: ignore[no-untyped-call]
    out: dict[str, Any] = {}
    for key in sorted(mp4.tags.keys()):
        out[key] = [
            bytes(v).decode() if isinstance(v, bytes) else list(v) if isinstance(v, tuple) else v
            for v in mp4.tags[key]
        ]
    return out


def check_golden(name: str, actual: dict[str, Any]) -> None:
    golden = FIXTURES / name
    if os.environ.get("UT_UPDATE_GOLDEN") == "1":
        golden.write_text(json.dumps(actual, indent=2, ensure_ascii=False) + "\n")
    assert actual == json.loads(golden.read_text())


@pytest.mark.parametrize(
    ("fixture", "kind", "golden"),
    [
        ("tone.opus", OPUS, "golden_opus_tags.json"),
        ("tone-faststart.m4a", M4A, "golden_m4a_tags.json"),
    ],
)
def test_tags_match_the_golden_file(
    tmp_path: Path, fixture: str, kind: ArchiveKind, golden: str
) -> None:
    path = copy_fixture(fixture, tmp_path / f"archive.{kind.ext}")
    audio_before = path.stat().st_size
    write_tags(path, kind, sample_metadata(title="Paper\x00 Moons (Live)"), GAIN)
    check_golden(golden, dump(path))
    assert path.stat().st_size > audio_before
    # Writing again replaces everything (nothing left from the previous tags).
    write_tags(path, kind, sample_metadata(genre=None, isrc=None, track_number=None), GAIN)
    tags = dump(path)
    assert "GENRE" not in tags
    assert "\xa9gen" not in tags
    assert "TRACKNUMBER" not in tags
    assert "trkn" not in tags


@pytest.mark.parametrize(("fixture", "kind"), [("tone.opus", OPUS), ("tone-faststart.m4a", M4A)])
def test_album_gain_is_rewritten_and_read_back(
    tmp_path: Path, fixture: str, kind: ArchiveKind
) -> None:
    path = copy_fixture(fixture, tmp_path / f"archive.{kind.ext}")
    assert read_track_gain(path, kind) is None
    write_tags(path, kind, sample_metadata(), GAIN)
    assert read_track_gain(path, kind) == GAIN
    write_replay_gain(path, kind, ALBUM)
    tags = dump(path)
    if kind == OPUS:
        assert tags["REPLAYGAIN_ALBUM_GAIN"] == ["-6.50 dB"]
        assert tags["R128_ALBUM_GAIN"] == ["-2944"]
        assert tags["TITLE"] == ["Paper Moons (Live)"]
    else:
        assert tags["----:com.apple.iTunes:replaygain_album_peak"] == ["0.998000"]
        assert tags["\xa9nam"] == ["Paper Moons (Live)"]
    write_replay_gain(path, kind, GAIN)
    tags = dump(path)
    assert not any("ALBUM_GAIN" in key.upper() for key in tags)
    assert read_track_gain(path, kind) == GAIN


def test_replay_gain_on_an_untagged_m4a(tmp_path: Path) -> None:
    path = copy_fixture("tone-faststart.m4a", tmp_path / "a.m4a")
    write_replay_gain(path, M4A, ALBUM)
    assert read_track_gain(path, M4A) == GAIN


def test_unreadable_gains_are_none(tmp_path: Path) -> None:
    path = copy_fixture("tone.opus", tmp_path / "a.opus")
    opus: Any = OggOpus(path)  # type: ignore[no-untyped-call]
    opus["REPLAYGAIN_TRACK_GAIN"] = ["loud", "+1.5 dB"]
    opus["REPLAYGAIN_TRACK_PEAK"] = ["-1", "x", "0.5"]
    opus.save()
    assert read_track_gain(path, OPUS) == ReplayGain(1.5, 0.5)
    opus["REPLAYGAIN_TRACK_GAIN"] = ["loud"]
    opus.save()
    assert read_track_gain(path, OPUS) is None
    assert read_track_gain(path, WEIRD) is None
    broken = tmp_path / "broken.opus"
    broken.write_bytes(b"OggS-not-really")
    assert read_track_gain(broken, OPUS) is None


def test_mp4_freeform_values_that_are_not_text_are_ignored(tmp_path: Path) -> None:
    path = copy_fixture("tone-faststart.m4a", tmp_path / "a.m4a")
    write_tags(path, M4A, sample_metadata(), GAIN)
    mp4: Any = MP4(path)  # type: ignore[no-untyped-call]
    mp4.tags["----:com.apple.iTunes:replaygain_track_gain"] = [b"not a gain"]
    mp4.save()
    assert read_track_gain(path, M4A) is None


@pytest.mark.parametrize("kind", [OPUS, M4A])
def test_broken_files_are_tagging_errors(tmp_path: Path, kind: ArchiveKind) -> None:
    path = tmp_path / f"broken.{kind.ext}"
    path.write_bytes(b"\x00" * 64)
    with pytest.raises(TaggingError, match="cannot tag"):
        write_tags(path, kind, sample_metadata(), GAIN)
    with pytest.raises(TaggingError, match="cannot tag"):
        write_replay_gain(path, kind, GAIN)


def test_other_formats_are_refused(tmp_path: Path) -> None:
    with pytest.raises(TaggingError, match="flac"):
        write_tags(tmp_path / "x.flac", WEIRD, sample_metadata(), GAIN)
    with pytest.raises(TaggingError, match="flac"):
        write_replay_gain(tmp_path / "x.flac", WEIRD, GAIN)


def test_r128_gain_is_clamped() -> None:
    comments = vorbis_comments(sample_metadata(), ReplayGain(200.0, 1.0, -200.0, 1.0))
    assert (comments["R128_TRACK_GAIN"], comments["R128_ALBUM_GAIN"]) == ("32767", "-32768")


def test_a_weak_match_has_few_tags() -> None:
    meta = sample_metadata(
        artist_sort=None,
        track_number=None,
        disc_number=None,
        total_tracks=None,
        total_discs=None,
        year=None,
        genre=None,
        release_type=None,
        isrc=None,
    )
    meta = type(meta)(**{**meta.__dict__, "musicbrainz": type(meta.musicbrainz)()})
    assert set(vorbis_comments(meta, GAIN)) == {
        "TITLE",
        "ARTIST",
        "ALBUMARTIST",
        "ALBUM",
        "REPLAYGAIN_TRACK_GAIN",
        "REPLAYGAIN_TRACK_PEAK",
        "R128_TRACK_GAIN",
    }
    assert set(mp4_atoms(meta, GAIN)) == {
        "\xa9nam",
        "\xa9ART",
        "aART",
        "\xa9alb",
        "----:com.apple.iTunes:replaygain_track_gain",
        "----:com.apple.iTunes:replaygain_track_peak",
    }


def test_an_m4a_without_any_tag_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """mutagen gives `tags is None` for an MP4 without an `ilst`; the fixture has one, so the
    loaded file is stripped in memory."""

    def bare(path: Path) -> Any:
        mp4: Any = MP4(path)  # type: ignore[no-untyped-call]
        mp4.tags = None
        return mp4

    monkeypatch.setattr(tags_module, "_open_mp4", bare)
    for name in ("a.m4a", "b.m4a"):
        copy_fixture("tone-faststart.m4a", tmp_path / name)
    write_tags(tmp_path / "a.m4a", M4A, sample_metadata(), GAIN)
    write_replay_gain(tmp_path / "b.m4a", M4A, GAIN)
    monkeypatch.undo()
    assert read_track_gain(tmp_path / "a.m4a", M4A) == GAIN
    assert read_track_gain(tmp_path / "b.m4a", M4A) == GAIN
