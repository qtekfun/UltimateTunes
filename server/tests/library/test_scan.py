# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The library scan: formats, tags, ReplayGain, grouping, rescans and the CLI command."""

import contextlib
import io
import threading
from pathlib import Path
from typing import Any

import mutagen.id3
import mutagen.mp4
import pytest

from tests.library.harness import LIGHTHOUSE_MBID, Harness
from tests.library.media import mp3_tags, write_flac, write_mp3, write_opus
from ultimatetunes.commands import CommandRegistry
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.storage import LocalLibraryStore
from ultimatetunes.library import cli
from ultimatetunes.library.scan import (
    LibraryScanner,
    fields_of,
    list_files,
    read_info,
    read_tags,
)
from ultimatetunes.settings import Settings

M: Any = mutagen


def scanner(lib: Harness) -> LibraryScanner:
    return LibraryScanner(lib.services.db, lib.services.library, lib.clock)


def track(lib: Harness, title: str) -> dict[str, object]:
    with lib.services.db.read() as conn:
        row = conn.execute("SELECT * FROM tracks WHERE title = ?", (title,)).fetchone()
    assert row is not None
    return dict(row)


def test_scan_registers_supported_files(lib: Harness) -> None:
    lighthouse = track(lib, "Lighthouse Keeper")
    assert lighthouse["status"] == "ready"
    assert lighthouse["path"] == "The Paper Lanterns/Harbour Lights/01 - Lighthouse Keeper.opus"
    assert lighthouse["format"] == "opus"
    assert lighthouse["content_type"] == "audio/ogg"
    assert lighthouse["track_number"] == 1
    assert lighthouse["disc_number"] == 1
    assert lighthouse["year"] == 2023
    assert lighthouse["duration_ms"] == 2000
    assert lighthouse["channels"] == 1
    assert lighthouse["musicbrainz_recording_id"] == LIGHTHOUSE_MBID
    # R128_TRACK_GAIN -541 (Q7.8, -23 LUFS) = -2.11 dB + 5 dB to the ReplayGain reference.
    assert lighthouse["rg_track_gain_db"] == pytest.approx(2.89)
    assert lighthouse["rg_track_peak"] == pytest.approx(0.988)
    assert lighthouse["title_norm"] == "lighthouse keeper"
    tidewater = track(lib, "Tidewater")
    assert tidewater["format"] == "mp3"
    assert tidewater["content_type"] == "audio/mpeg"
    assert tidewater["rg_track_gain_db"] == pytest.approx(-6.40)
    assert tidewater["rg_album_gain_db"] == pytest.approx(-6.85)
    assert tidewater["bit_rate_kbps"] == 128
    assert tidewater["sample_rate_hz"] == 44100
    assert tidewater["album_id"] == lighthouse["album_id"]
    brasas = track(lib, "Brasas")
    assert brasas["format"] == "flac"
    assert brasas["duration_ms"] == 3000
    assert lib.one("SELECT COUNT(*) FROM tracks") == 3
    assert lib.one("SELECT COUNT(*) FROM albums") == 2
    assert lib.one("SELECT COUNT(*) FROM artists") == 2
    cover = lib.one("SELECT cover_path FROM albums WHERE name = 'Harbour Lights'")
    assert cover == "The Paper Lanterns/Harbour Lights/cover.jpg"
    assert lib.one("SELECT name_norm FROM albums WHERE name = 'Salt & Ember'") == "salt ember"
    assert lib.one("SELECT sort_name FROM artists WHERE name = 'The Paper Lanterns'") == (
        "Paper Lanterns, The"
    )


def test_rescan_is_incremental_and_never_deletes(lib: Harness) -> None:
    result = scanner(lib).scan()
    assert (result.added, result.updated, result.unchanged) == (0, 0, 3)
    assert result.skipped == 3  # notes.txt, clip.wav, cover.jpg (hidden files are not listed)
    write_opus(
        lib.music / "The Paper Lanterns" / "Harbour Lights" / "01 - Lighthouse Keeper.opus",
        {
            "title": "Lighthouse Keeper (Remastered)",
            "artist": "The Paper Lanterns",
            "album": "Harbour Lights",
            "tracknumber": "1",
            "comment": "a longer tag" * 20,
        },
    )
    (lib.music / "Marisol Vega" / "Salt & Ember" / "03 - Brasas.flac").unlink()
    result = scanner(lib).scan()
    assert (result.added, result.updated, result.unchanged, result.missing) == (0, 1, 1, 1)
    assert lib.one("SELECT COUNT(*) FROM tracks") == 3
    assert lib.one("SELECT title FROM tracks WHERE track_number = 1 AND format = 'opus'") == (
        "Lighthouse Keeper (Remastered)"
    )
    full = scanner(lib).scan(full=True)
    assert full.updated == 2


def test_scan_reports_unreadable_files(lib: Harness) -> None:
    (lib.music / "broken.mp3").write_bytes(b"not an mp3 at all")
    (lib.music / "empty.flac").write_bytes(b"")
    result = scanner(lib).scan()
    assert result.failed == 2
    assert any("broken.mp3" in e for e in result.errors)


def test_scan_groups_by_album_artist_and_musicbrainz(lib: Harness, tmp_path: Path) -> None:
    various = lib.music / "Various" / "Night Mix"
    write_mp3(
        various / "01.mp3",
        mp3_tags(
            "Neon",
            "Neon Harbor",
            "Night Mix",
            album_artist="Various Artists",
            extra={
                "MusicBrainz Album Id": "11111111-2222-4333-8444-555555555555",
                "MusicBrainz Artist Id": "aaaaaaaa-2222-4333-8444-555555555555",
            },
            recording="rec-1",
        ),
    )
    write_mp3(
        various / "02.mp3",
        mp3_tags(
            "Tide",
            "Marisol Vega",
            "Night Mix (Deluxe)",
            album_artist="Various Artists",
            track="2",
            extra={"MusicBrainz Album Id": "11111111-2222-4333-8444-555555555555"},
        ),
    )
    scanner(lib).scan()
    ids = lib.ids()
    assert lib.one("SELECT COUNT(*) FROM albums WHERE musicbrainz_release_id IS NOT NULL") == 1
    neon = track(lib, "Neon")
    tide = track(lib, "Tide")
    assert neon["album_id"] == tide["album_id"]
    assert tide["artist_id"] == ids["Marisol Vega"]
    assert neon["musicbrainz_recording_id"] == "rec-1"
    album_artist = lib.one("SELECT artist_id FROM albums WHERE id = ?", (neon["album_id"],))
    assert album_artist == ids["Various Artists"]
    assert lib.one("SELECT musicbrainz_id FROM artists WHERE name = 'Neon Harbor'") == (
        "aaaaaaaa-2222-4333-8444-555555555555"
    )
    # A file with the same artist MBID but another spelling joins the same artist.
    write_mp3(
        various / "03.mp3",
        mp3_tags(
            "Glow",
            "NEON HARBOR",
            "Night Mix",
            album_artist="Various Artists",
            extra={"MusicBrainz Artist Id": "aaaaaaaa-2222-4333-8444-555555555555"},
        ),
    )
    scanner(lib).scan()
    assert track(lib, "Glow")["artist_id"] == neon["artist_id"]


def test_scan_without_tags_uses_the_file_name(lib: Harness) -> None:
    write_flac(lib.music / "loose" / "Untitled Demo.flac", {})
    scanner(lib).scan()
    demo = track(lib, "Untitled Demo")
    assert demo["artist_name"] == "Unknown Artist"
    assert demo["album_name"] == "Unknown Album"


def test_artist_mbid_is_added_to_an_existing_artist(lib: Harness) -> None:
    write_flac(
        lib.music / "x" / "song.flac",
        {
            "title": "Later",
            "artist": "Marisol Vega",
            "musicbrainz_artistid": "bbbbbbbb-2222-4333-8444-555555555555",
        },
    )
    write_flac(
        lib.music / "x" / "other.flac",
        {
            "title": "Other",
            "artist": "Marisol Vega",
            "musicbrainz_artistid": "cccccccc-2222-4333-8444-555555555555",
        },
    )
    scanner(lib).scan()
    assert lib.one("SELECT musicbrainz_id FROM artists WHERE id = ?", (lib.ids()["Marisol Vega"],))
    # Another MBID for the same name is another artist (a namesake).
    assert lib.one("SELECT COUNT(*) FROM artists WHERE name = 'Marisol Vega'") == 2


def test_stop_ends_the_scan_early(lib: Harness) -> None:
    stop = threading.Event()
    stop.set()
    result = scanner(lib).scan(stop=stop)
    assert (result.added, result.unchanged, result.skipped) == (0, 0, 0)


def test_list_files_skips_links_and_hidden_paths(lib: Harness, tmp_path: Path) -> None:
    outside = tmp_path / "outside.opus"
    outside.write_bytes(b"x")
    (lib.music / "link.opus").symlink_to(outside)
    (lib.music / ".cache").mkdir()
    (lib.music / ".cache" / "x.opus").write_bytes(b"x")
    files = list(list_files(lib.services.library))
    assert "link.opus" not in files
    assert ".hidden.opus" not in files
    assert not any(f.startswith(".cache") for f in files)
    assert list(list_files(LocalLibraryStore(tmp_path / "missing"))) == []


def test_a_refused_path_does_not_end_the_scan(lib: Harness) -> None:
    store = lib.services.library
    real_walk = store.walk

    def walk() -> Any:
        yield "bad\\name.opus"
        yield from real_walk()

    lib.services.library.walk = walk  # type: ignore[method-assign]
    files = list(list_files(store))
    assert "bad\\name.opus" not in files
    assert "Marisol Vega/Salt & Ember/03 - Brasas.flac" in files
    assert scanner(lib).scan().unchanged == 3


def test_read_tags_numbers_and_gains() -> None:
    tags = read_tags(
        {
            "tracknumber": ["7"],
            "tracktotal": ["12"],
            "discnumber": ["2/3"],
            "date": ["1999-01-01"],
            "replaygain_track_gain": ["+1.5 dB"],
            "replaygain_album_gain": ["junk"],
            "r128_album_gain": ["256"],
            "replaygain_album_peak": ["1.0"],
        }
    )
    assert (tags.track, tags.total_tracks, tags.disc, tags.total_discs) == (7, 12, 2, 3)
    assert tags.year == 1999
    assert tags.rg_track_gain == 1.5
    assert tags.rg_album_gain == 6.0
    assert tags.rg_album_peak == 1.0
    empty = read_tags({"tracknumber": ["x"], "r128_track_gain": ["n/a"], "date": ["unknown"]})
    assert (empty.track, empty.rg_track_gain, empty.year) == (None, None, None)


def test_fields_of_id3_and_mp4() -> None:
    id3 = M.id3.ID3()
    id3.add(M.id3.TPOS(encoding=3, text="1/2"))
    id3.add(M.id3.TXXX(encoding=3, desc="MusicBrainz Release Track Id", text="rt-1"))
    id3.add(M.id3.UFID(owner="http://example.org", data=b"ignored"))
    assert fields_of(id3) == {"discnumber": ["1/2"], "musicbrainz_releasetrackid": ["rt-1"]}
    mp4 = M.mp4.MP4Tags()
    mp4["\xa9nam"] = ["Song"]
    mp4["trkn"] = [(3, 10)]
    mp4["disk"] = [(1, 0)]
    mp4["----:com.apple.iTunes:replaygain_track_gain"] = [b"-3.00 dB"]
    mp4["----:com.apple.iTunes:MusicBrainz Track Id"] = [b"rec-9"]
    fields = fields_of(mp4)
    assert fields["title"] == ["Song"]
    assert fields["tracknumber"] == ["3"]
    assert fields["tracktotal"] == ["10"]
    assert fields["discnumber"] == ["1"]
    assert "disctotal" not in fields or fields["disctotal"] == []
    assert fields["replaygain_track_gain"] == ["-3.00 dB"]
    assert fields["musicbrainz_trackid"] == ["rec-9"]
    assert fields_of(None) == {}
    assert fields_of({"TITLE": "x"}) == {"title": ["x"]}


def test_read_info_estimates_the_bit_rate() -> None:
    class Info:
        length = 2.0
        bitrate = 0
        sample_rate = 0
        channels = 2

    info = read_info(Info(), 32000)
    assert info.bit_rate_kbps == 128
    assert info.sample_rate_hz is None
    assert read_info(object(), 10).duration_ms is None


def test_cli_scan(settings: Settings, clock: FakeClock, tmp_path: Path) -> None:
    from tests.library.harness import make_harness  # noqa: PLC0415

    harness = make_harness(settings, clock)
    lib = next(harness)  # the generator stays open: the test client runs until the end
    out = io.StringIO()
    assert cli.run_scan(settings, [], out=out) == 0
    assert "unchanged 3" in out.getvalue()
    assert cli.run_scan(settings, ["--full"], out=out) == 0
    assert cli.run_scan(settings, ["--nope"], out=out) == 2
    (lib.music / "bad.opus").write_bytes(b"OggS-not-really")
    assert cli.run_scan(settings, [], out=out) == 1
    registry = CommandRegistry()
    cli.register(registry)
    assert registry.get("scan-library").run is cli.run_scan
    with contextlib.suppress(StopIteration):
        next(harness)


@pytest.mark.parametrize(("state", "registered"), [("tagging", False), ("ready", True)])
def test_scan_leaves_paths_reserved_by_running_jobs(
    lib: Harness, state: str, registered: bool
) -> None:
    rel = "Neon Harbor/Static Bloom/01 - Static Bloom.opus"
    write_opus(lib.music / rel, {"title": "Static Bloom", "artist": "Neon Harbor"})
    now = "2026-10-12T08:00:00.000Z"
    with lib.services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, yt_video_id,"
            " created_at, updated_at) VALUES ('0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0f1', 'pending',"
            " 'Static Bloom', 'static bloom', 'Neon Harbor', 'Hm3Vx8Nq2Lp', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO jobs (id, kind, track_id, yt_video_id, state, library_path, created_at,"
            " updated_at) VALUES ('0199d6a2-4c1e-7b3a-9f10-2a6c8e01d0f1', 'download',"
            " '0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0f1', 'Hm3Vx8Nq2Lp', ?, ?, ?, ?)",
            (state, rel, now, now),
        )
    result = scanner(lib).scan()
    assert result.reserved == (0 if registered else 1)
    assert (lib.one("SELECT COUNT(*) FROM tracks WHERE path = ?", (rel,)) == 1) is registered
