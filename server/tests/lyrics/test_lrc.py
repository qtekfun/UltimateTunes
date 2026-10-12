# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""LRC parsing: timings, metadata, offset, enhanced tags and malformed input."""

import pytest

from ultimatetunes.lyrics.lrc import MAX_LINE_CHARS, MAX_LINES, TimedLine, parse_lrc, plain_lines


def test_parses_the_contract_example() -> None:
    parsed = parse_lrc(
        "[00:00.00] Salt on the window\n[00:04.21] I keep the light\n[00:09.875] Turning\n"
    )
    assert parsed.lines == (
        TimedLine(0, "Salt on the window"),
        TimedLine(4210, "I keep the light"),
        TimedLine(9875, "Turning"),
    )
    assert parsed.untimed == ()
    assert parsed.offset_ms == 0


@pytest.mark.parametrize(
    ("tag", "ms"),
    [
        ("[00:01]", 1000),
        ("[00:01.5]", 1500),
        ("[00:01.05]", 1050),
        ("[00:01.005]", 1005),
        ("[00:01:50]", 1500),
        ("[1:02.30]", 62300),
        ("[75:00.00]", 4_500_000),
        ("[100:00.00]", 6_000_000),
    ],
)
def test_time_tag_forms(tag: str, ms: int) -> None:
    assert parse_lrc(f"{tag}text").lines == (TimedLine(ms, "text"),)


def test_repeated_tags_give_one_line_each_sorted_by_time() -> None:
    parsed = parse_lrc("[00:30.00][00:10.00] Chorus\n[00:20.00] Verse\n")
    assert parsed.lines == (
        TimedLine(10000, "Chorus"),
        TimedLine(20000, "Verse"),
        TimedLine(30000, "Chorus"),
    )


def test_equal_starts_keep_file_order() -> None:
    parsed = parse_lrc("[00:05.00]first\n[00:05.00]second\n")
    assert [line.text for line in parsed.lines] == ["first", "second"]


def test_metadata_is_dropped_and_offset_applied() -> None:
    parsed = parse_lrc(
        "﻿[ar:The Paper Lanterns]\n[ti:Lighthouse Keeper]\n[offset:+500]\n"
        "[00:00.20]early\n[00:02.00]later\n"
    )
    assert parsed.offset_ms == 500
    # A positive offset makes lyrics appear sooner, never before 0.
    assert parsed.lines == (TimedLine(0, "early"), TimedLine(1500, "later"))
    assert parsed.untimed == ()


def test_negative_offset_delays_lyrics() -> None:
    parsed = parse_lrc("[offset:-250]\n[00:01.00]x\n")
    assert parsed.lines == (TimedLine(1250, "x"),)


@pytest.mark.parametrize("value", ["abc", "", "+", "1.5", "99999999"])
def test_malformed_offset_is_ignored(value: str) -> None:
    parsed = parse_lrc(f"[offset:{value}]\n[00:01.00]x\n")
    assert parsed.offset_ms == 0
    assert parsed.lines == (TimedLine(1000, "x"),)


def test_offset_zero_overrides_an_earlier_one() -> None:
    assert parse_lrc("[offset:300]\n[offset:0]\n[00:01.00]x\n").offset_ms == 0


def test_enhanced_word_tags_are_removed() -> None:
    parsed = parse_lrc("[00:01.00]<00:01.00>Salt <00:01.40>on <00:01.90>the window\n")
    assert parsed.lines == (TimedLine(1000, "Salt on the window"),)


def test_empty_timed_lines_are_kept() -> None:
    parsed = parse_lrc("[00:01.00]words\n[00:05.00]\n[00:06.00]   \n")
    assert parsed.lines == (TimedLine(1000, "words"), TimedLine(5000, ""), TimedLine(6000, ""))


def test_malformed_lines_never_raise() -> None:
    parsed = parse_lrc(
        "[00:75.00]bad seconds\n"
        "[00:61.00]\n"
        "[aa:bb]\n"
        "[aa:bb]text after a tag\n"
        "[Chorus]\n"
        "no tag at all\n"
        "[00:10.00][00:99.00]half valid\n"
        "[00:1x.00]broken\n"
        "\n   \n"
        "[]\n"
        "[00:20.00]good\n"
    )
    assert parsed.lines == (TimedLine(10000, "half valid"), TimedLine(20000, "good"))
    assert parsed.untimed == (
        "bad seconds",
        "[aa:bb]text after a tag",
        "[Chorus]",
        "no tag at all",
        "[00:1x.00]broken",
        "[]",
    )


def test_a_file_without_time_tags_has_only_untimed_text() -> None:
    parsed = parse_lrc("[ti:Song]\nfirst line\nsecond line\n")
    assert parsed.lines == ()
    assert parsed.untimed == ("first line", "second line")


def test_windows_line_endings() -> None:
    parsed = parse_lrc("[00:01.00]a\r\n[00:02.00]b\r\n")
    assert parsed.lines == (TimedLine(1000, "a"), TimedLine(2000, "b"))


def test_absurd_input_is_bounded() -> None:
    long_line = "[00:01.00]" + "x" * (MAX_LINE_CHARS * 3)
    parsed = parse_lrc("\n".join([long_line] * (MAX_LINES + 50)))
    assert len(parsed.lines) == MAX_LINES
    assert len(parsed.lines[0].text) == MAX_LINE_CHARS


def test_plain_lines_trim_outer_blanks_and_keep_stanzas() -> None:
    text = "﻿\n\nGulls on the railing  \n\nNobody waiting\r\n\n"
    assert plain_lines(text) == ["Gulls on the railing", "", "Nobody waiting"]


def test_plain_lines_of_blank_text() -> None:
    assert plain_lines(" \n\n ") == []
