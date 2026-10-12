# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Path sanitizer (100 % coverage, SECURITY.md): malicious metadata always ends inside the
library, through the real `LocalLibraryStore`."""

import random
import unicodedata
from pathlib import Path

import pytest

from ultimatetunes.core.storage import LocalLibraryStore, check_relative
from ultimatetunes.errors import PathRejected
from ultimatetunes.paths import (
    COVER_NAME,
    album_dir,
    cover_path,
    library_path,
    sanitize_component,
    track_file_name,
)
from ultimatetunes.paths.sanitize import MAX_COMPONENT_BYTES, truncate_utf8

MALICIOUS = [
    "..",
    ".",
    "../../etc/passwd",
    "/etc/passwd",
    "a/../../b",
    "..\\..\\windows",
    "evil\x00name",
    "\x00",
    "line\nbreak\ttab\r",
    "\u202eevil\u202dgpj.exe",  # bidi override
    "zero\u200bwidth\ufeff",
    "\uff0e\uff0e\uff0fetc",  # fullwidth "../"
    "\u2025",  # two dot leader, NFKC ".."
    "\u2024\u2024/x",
    "CON",
    "con.txt",
    "Lpt1",
    "COM\u00b9",
    "NUL .mp3",
    "   ",
    "...",
    "-rf",
    'a:b*c?d"e<f>g|h',
    "x" * 300,
    "\U0001f3b5" * 300,  # 4-byte characters
    "e\u0301" * 200,  # combining marks
    "\ud800",  # lone surrogate
    "\ue000private",
    "\u2028para\u2029",
    "trailing dot.",
    " .hidden",
]


def test_known_names_are_kept_readable() -> None:
    assert sanitize_component("The Paper Lanterns", fallback="X") == "The Paper Lanterns"
    assert sanitize_component("AC/DC", fallback="X") == "AC_DC"
    assert sanitize_component("  What?  Now: Yes  ", fallback="X") == "What_ Now_ Yes"
    assert sanitize_component("Bj\u00f6rk", fallback="X") == "Bj\u00f6rk"
    assert sanitize_component("\u202eevil\u202d", fallback="X") == "evil"
    assert sanitize_component("tab\there", fallback="X") == "tab here"
    assert sanitize_component("x\u00a0y", fallback="X") == "x y"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("..", "Fallback"),
        ("...", "Fallback"),
        ("\u2025", "Fallback"),
        ("   ", "Fallback"),
        ("\x00", "Fallback"),
        ("CON", "_CON"),
        ("con.txt", "_con.txt"),
        ("Lpt1", "_Lpt1"),
        ("COM\u00b9", "_COM1"),
        ("NUL .mp3", "_NUL .mp3"),
        ("CONCERT", "CONCERT"),
        (" .hidden", "hidden"),
        ("trailing dot.", "trailing dot"),
        ("../../etc/passwd", "_.._etc_passwd"),
    ],
)
def test_dangerous_names(text: str, expected: str) -> None:
    assert sanitize_component(text, fallback="Fallback") == expected


@pytest.mark.parametrize("text", MALICIOUS)
def test_every_component_is_safe(text: str) -> None:
    name = sanitize_component(text, fallback="Fallback")
    assert name
    assert name not in (".", "..")
    assert not name.startswith(".")
    assert not name.endswith((".", " "))
    assert "/" not in name
    assert "\\" not in name
    assert "\x00" not in name
    assert len(name.encode("utf-8")) <= MAX_COMPONENT_BYTES
    assert all(unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co", "Cn") for ch in name)
    assert check_relative(name) == name


def test_long_names_are_cut_on_a_character_boundary() -> None:
    name = sanitize_component("\U0001f3b5" * 300, fallback="X", max_bytes=10)
    assert name == "\U0001f3b5\U0001f3b5"
    assert truncate_utf8("abc", 10) == "abc"
    assert truncate_utf8("\u00f1and\u00fa", 3) == "\u00f1a"


def test_the_reserved_prefix_still_fits() -> None:
    assert sanitize_component("CON", fallback="X", max_bytes=4) == "_CON"
    assert len(sanitize_component("CONX" * 50, fallback="X", max_bytes=4)) <= 4


@pytest.mark.parametrize("fallback", ["", "..", "a/b", "CON", " padded"])
def test_an_unsafe_fallback_is_a_bug(fallback: str) -> None:
    with pytest.raises(ValueError, match="fallback"):
        sanitize_component("x", fallback=fallback)


def test_max_bytes_must_leave_room() -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        sanitize_component("x", fallback="X", max_bytes=1)


def test_the_layout() -> None:
    path = library_path(
        artist="The Paper Lanterns",
        album="Lanterns at Dusk",
        title="Paper Moons (Live)",
        ext="opus",
        track_number=4,
    )
    assert path == "The Paper Lanterns/Lanterns at Dusk/04 - Paper Moons (Live).opus"
    assert track_file_name("T", "m4a") == "T.m4a"
    assert track_file_name("T", "m4a", track_number=12, disc_number=1) == "12 - T.m4a"
    assert track_file_name("T", "m4a", track_number=3, disc_number=2) == "2-03 - T.m4a"
    assert track_file_name("T", "m4a", track_number=0) == "T.m4a"
    assert track_file_name("T", "m4a", track_number=1000) == "T.m4a"
    assert track_file_name("T", "opus", track_number=7, suffix="Qx7Lm2pZ0aB") == (
        "07 - T (Qx7Lm2pZ0aB).opus"
    )
    assert track_file_name("", "opus") == "Untitled.opus"
    assert album_dir("", "..") == "Unknown Artist/Unknown Album"
    assert cover_path("A/B", "C") == f"A_B/C/{COVER_NAME}"


@pytest.mark.parametrize("ext", ["mp3", "", "opus/../x", "../opus", "OPUS"])
def test_only_archive_extensions(ext: str) -> None:
    with pytest.raises(PathRejected):
        track_file_name("T", ext)


def test_long_titles_keep_the_extension() -> None:
    name = track_file_name("x" * 300, "opus", track_number=1, suffix="y" * 300)
    assert name.endswith(".opus")
    assert name.startswith("01 - xxx")
    assert len(name.encode("utf-8")) <= MAX_COMPONENT_BYTES


def _inside(store: LocalLibraryStore, root: Path, rel: str) -> None:
    resolved = store.local_path(rel)
    assert resolved.is_relative_to(root.resolve())
    assert resolved != root.resolve()
    assert len(rel.split("/")) == 3  # Artist/Album/file


@pytest.mark.parametrize("text", MALICIOUS)
def test_malicious_metadata_ends_inside_the_library(tmp_path: Path, text: str) -> None:
    store = LocalLibraryStore(tmp_path)
    for rel in (
        library_path(artist=text, album=text, title=text, ext="opus", track_number=1),
        library_path(artist=text, album=text, title=text, ext="m4a", suffix=text),
        cover_path(text, text),
    ):
        _inside(store, tmp_path, rel)
        with store.open_write(rel) as out:
            out.write(b"x")
        assert store.exists(rel)


def test_random_metadata_ends_inside_the_library(tmp_path: Path) -> None:
    """A seeded fuzz over separators, dots, controls and odd code points."""
    store = LocalLibraryStore(tmp_path)
    rng = random.Random(9)  # noqa: S311 - test data, not crypto
    alphabet = ["/", "\\", ".", "..", "\x00", "\n", " ", "\u202e", "\uff0f", "\u2025", "a"]
    alphabet += ["\u03a9", "CON", "\U0001f3b5", "\ud800", ":", "\u200b"]
    for _ in range(500):
        parts = ["".join(rng.choices(alphabet, k=rng.randint(0, 40))) for _ in range(3)]
        rel = library_path(
            artist=parts[0],
            album=parts[1],
            title=parts[2],
            ext=rng.choice(["opus", "m4a"]),
            track_number=rng.randint(-1, 1200),
            disc_number=rng.randint(-1, 3),
        )
        _inside(store, tmp_path, rel)


@pytest.mark.parametrize("title", ["x" * 300, "\u65e5\u672c\u8a9e\u306e\u6b4c" * 60])
def test_the_suffix_survives_long_titles(title: str) -> None:
    name = track_file_name(title, "opus", track_number=4, suffix="Qx7Lm2pZ0aB")
    assert name.startswith("04 - ")
    assert name.endswith(" (Qx7Lm2pZ0aB).opus")
    assert len(name.encode("utf-8")) <= MAX_COMPONENT_BYTES
    long_suffix = track_file_name("T", "m4a", suffix="/" * 300)
    assert long_suffix.startswith("T (_")
    assert len(long_suffix.encode("utf-8")) <= MAX_COMPONENT_BYTES
