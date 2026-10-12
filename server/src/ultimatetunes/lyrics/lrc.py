# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""LRC parsing for `getLyricsBySongId`.

LRC is a line format: `[mm:ss.xx]text`. What this parser accepts:
- one or more time tags at the start of a line (`[00:12.00][01:30.50]Chorus`), each giving
  its own line; minutes may exceed 59, the fraction may have 1 to 3 digits (`.5` is 500 ms,
  `.12` is 120 ms, `.123` is 123 ms) and may be written after `:` instead of `.`;
- metadata tags (`[ar:...]`, `[ti:...]`); only `[offset:±ms]` is used. A positive offset makes
  the lyrics appear sooner, so it is subtracted from every start (never below 0);
- word timings of "enhanced" LRC (`<00:12.30>word`), which are removed from the text.

Malformed input never raises: time tags that are not valid times (`[00:75.00]`) are skipped,
and a line left without a valid time tag (or with none at all) is not a synced line. Its text
is kept in `untimed`, so a file without a single valid time tag can still be shown as plain
lyrics. Lines are sorted by start
time (stable, so equal starts keep their order). Empty texts are kept: in synced lyrics they
mark where a line ends (instrumental breaks).
"""

import re
from dataclasses import dataclass

# Upper bounds against absurd upstream input; real songs have a few hundred lines at most.
MAX_LINES = 5000
MAX_LINE_CHARS = 1000

_TIME_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_META_TAG = re.compile(r"^\[([A-Za-z#][A-Za-z#]*):(.*)\]$")
_WORD_TAG = re.compile(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>")
_OFFSET = re.compile(r"^[+-]?\d{1,7}$")
_SECONDS_PER_MINUTE = 60


@dataclass(frozen=True)
class TimedLine:
    start_ms: int
    text: str


@dataclass(frozen=True)
class ParsedLrc:
    lines: tuple[TimedLine, ...]
    # Text of the lines without a valid time tag (metadata excluded), in file order.
    untimed: tuple[str, ...]
    offset_ms: int


def _clean(text: str) -> str:
    return _WORD_TAG.sub("", text).strip()[:MAX_LINE_CHARS]


def _tag_ms(match: re.Match[str]) -> int | None:
    minutes, seconds, fraction = match.group(1), match.group(2), match.group(3)
    if int(seconds) >= _SECONDS_PER_MINUTE:
        return None
    millis = int(fraction.ljust(3, "0")) if fraction else 0
    return (int(minutes) * _SECONDS_PER_MINUTE + int(seconds)) * 1000 + millis


def _split_tags(line: str) -> tuple[list[int], str]:
    """The valid leading time tags of `line` (in ms) and the remaining text. Tags that look
    like times but are not (`[00:75.00]`) are skipped."""
    starts: list[int] = []
    rest = line
    while (match := _TIME_TAG.match(rest)) is not None:
        start = _tag_ms(match)
        if start is not None:
            starts.append(start)
        rest = rest[match.end() :].lstrip(" \t")
    return starts, rest


def _offset(value: str) -> int | None:
    value = value.strip()
    return int(value) if _OFFSET.match(value) else None


def parse_lrc(text: str) -> ParsedLrc:
    """Parses LRC text. Never raises; see the module docstring for what is accepted."""
    timed: list[TimedLine] = []
    untimed: list[str] = []
    offset_ms = 0
    for raw in text.lstrip("﻿").splitlines()[:MAX_LINES]:
        line = raw.strip()
        if not line:
            continue
        starts, rest = _split_tags(line)
        if starts:
            timed.extend(TimedLine(start, _clean(rest)) for start in starts)
            continue
        meta = _META_TAG.match(line)
        if meta is not None:
            value = _offset(meta.group(2)) if meta.group(1).lower() == "offset" else None
            if value is not None:
                offset_ms = value
            continue
        cleaned = _clean(rest)
        if cleaned:
            untimed.append(cleaned)
    shifted = sorted(
        (TimedLine(max(0, line.start_ms - offset_ms), line.text) for line in timed),
        key=lambda line: line.start_ms,
    )
    return ParsedLrc(tuple(shifted), tuple(untimed), offset_ms)


def plain_lines(text: str) -> list[str]:
    """Plain lyrics as lines: trailing spaces and word tags removed, blank lines inside the
    text kept (stanza breaks), leading and trailing blank lines dropped."""
    lines = [_clean(line) for line in text.lstrip("﻿").splitlines()[:MAX_LINES]]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines
