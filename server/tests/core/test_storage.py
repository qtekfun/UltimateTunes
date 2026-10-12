# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Storage interfaces stay inside their roots, whatever the path says."""

from pathlib import Path

import pytest

from ultimatetunes.core.storage import LocalLibraryStore, LocalStagingStore, check_relative
from ultimatetunes.errors import Conflict, PathRejected


@pytest.fixture
def staging(tmp_path: Path) -> LocalStagingStore:
    (tmp_path / "staging").mkdir()
    return LocalStagingStore(tmp_path / "staging")


@pytest.fixture
def library(tmp_path: Path) -> LocalLibraryStore:
    (tmp_path / "music").mkdir()
    return LocalLibraryStore(tmp_path / "music")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "/etc/passwd",
        "../outside",
        "a/../../outside",
        "a/./b",
        "a//b",
        "a/",
        ".",
        "a\\..\\b",
        "nul\x00byte",
        "x" * 1025,
    ],
)
def test_bad_paths_are_rejected(staging: LocalStagingStore, bad: str) -> None:
    with pytest.raises(PathRejected):
        staging.local_path(bad)
    with pytest.raises(PathRejected):
        staging.check(bad)


def test_symlinks_cannot_escape(staging: LocalStagingStore, tmp_path: Path) -> None:
    (tmp_path / "secret").mkdir()
    (staging.root / "link").symlink_to(tmp_path / "secret")
    with pytest.raises(PathRejected, match="escapes"):
        staging.open_write("link/file")
    assert check_relative("job/a.webm") == "job/a.webm"


def test_write_append_read_rename_delete(staging: LocalStagingStore) -> None:
    with staging.open_write("job1/a.part") as out:
        out.write(b"abc")
    with staging.open_write("job1/a.part", append=True) as out:
        out.write(b"def")
    assert staging.size("job1/a.part") == 6
    staging.rename("job1/a.part", "job1/a.webm")
    assert not staging.exists("job1/a.part")
    with staging.open_read("job1/a.webm") as reader:
        assert reader.read() == b"abcdef"
    staging.delete("job1/a.webm")
    staging.delete("job1/missing")
    with staging.open_write("job2/b") as out:
        out.write(b"x")
    staging.delete("job2")
    assert not staging.exists("job2")


def test_import_file_is_atomic_and_never_overwrites(
    staging: LocalStagingStore, library: LocalLibraryStore
) -> None:
    with staging.open_write("job/a.opus") as out:
        out.write(b"audio")
    library.import_file(staging, "job/a.opus", "Artist/Album/01 - Song.opus")
    with library.open_read("Artist/Album/01 - Song.opus") as reader:
        assert reader.read() == b"audio"
    with pytest.raises(Conflict):
        library.import_file(staging, "job/a.opus", "Artist/Album/01 - Song.opus")
    assert [p.name for p in (library.root / "Artist" / "Album").iterdir()] == ["01 - Song.opus"]


def test_import_file_races_end_in_conflict(
    staging: LocalStagingStore, library: LocalLibraryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    with staging.open_write("job/a.opus") as out:
        out.write(b"audio")
    monkeypatch.setattr(Path, "exists", lambda _self: False)
    (library.root / "song.opus").write_bytes(b"other")
    with pytest.raises(Conflict):
        library.import_file(staging, "job/a.opus", "song.opus")
    assert (library.root / "song.opus").read_bytes() == b"other"


def test_writable_and_usage(staging: LocalStagingStore, tmp_path: Path) -> None:
    assert staging.is_writable()
    usage = staging.usage()
    assert usage.total_bytes >= usage.free_bytes > 0
    assert not LocalStagingStore(tmp_path / "missing").is_writable()


def test_delete_removes_a_file_symlink_never_its_target(
    staging: LocalStagingStore, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me")
    inside = staging.root / "inside.txt"
    inside.write_text("keep me too")
    (staging.root / "job").mkdir()
    (staging.root / "job" / "out").symlink_to(outside)
    (staging.root / "job" / "in").symlink_to(inside)
    staging.delete("job/out")
    staging.delete("job/in")
    assert not (staging.root / "job" / "out").is_symlink()
    assert not (staging.root / "job" / "in").is_symlink()
    assert outside.read_text() == "keep me"
    assert inside.read_text() == "keep me too"


def test_delete_removes_a_directory_symlink_never_its_target(
    staging: LocalStagingStore, tmp_path: Path
) -> None:
    target = tmp_path / "precious"
    target.mkdir()
    (target / "song.opus").write_bytes(b"audio")
    (staging.root / "link").symlink_to(target)
    staging.delete("link")
    assert not (staging.root / "link").exists()
    assert (target / "song.opus").read_bytes() == b"audio"
    # A symlink inside a deleted directory is unlinked, not followed.
    (staging.root / "job").mkdir()
    (staging.root / "job" / "link").symlink_to(target)
    staging.delete("job")
    assert not (staging.root / "job").exists()
    assert (target / "song.opus").read_bytes() == b"audio"


def test_rename_moves_the_symlink_itself(staging: LocalStagingStore, tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    (staging.root / "a").symlink_to(target)
    staging.rename("a", "moved/b")
    moved = staging.root / "moved" / "b"
    assert moved.is_symlink()
    assert moved.readlink() == target
    assert not (staging.root / "a").is_symlink()
    assert target.is_dir()


def test_entry_paths_must_stay_inside(staging: LocalStagingStore, tmp_path: Path) -> None:
    (tmp_path / "secret").mkdir()
    (staging.root / "dir").symlink_to(tmp_path / "secret")
    with pytest.raises(PathRejected, match="escapes"):
        staging.delete("dir/file")
    with pytest.raises(PathRejected, match="escapes"):
        staging.rename("x", "dir/file")
    with pytest.raises(PathRejected):
        staging.delete("../x")


def test_walk_lists_files_and_skips_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "music"
    (root / "B" / "Album").mkdir(parents=True)
    (root / "A").mkdir()
    (root / "A" / "2.opus").write_bytes(b"x")
    (root / "A" / "1.opus").write_bytes(b"x")
    (root / "B" / "Album" / "01 - Song.m4a").write_bytes(b"x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.opus").write_bytes(b"x")
    (root / "A" / "link.opus").symlink_to(outside / "secret.opus")
    (root / "dirlink").symlink_to(outside, target_is_directory=True)
    store = LocalLibraryStore(root)
    assert list(store.walk()) == ["A/1.opus", "A/2.opus", "B/Album/01 - Song.m4a"]


def test_walk_of_a_missing_root_is_empty(tmp_path: Path) -> None:
    assert list(LocalLibraryStore(tmp_path / "nope").walk()) == []
