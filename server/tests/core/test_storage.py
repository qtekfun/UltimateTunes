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
