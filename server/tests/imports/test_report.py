# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The CSV match report never lets a cell run as a spreadsheet formula."""

import csv
import io

import pytest

from ultimatetunes.imports.report import HEADER, csv_report, escape_cell
from ultimatetunes.imports.repository import ItemRow, TrackRow


@pytest.mark.parametrize(
    ("value", "escaped"),
    [
        ('=HYPERLINK("http://x")', '\'=HYPERLINK("http://x")'),
        ("+1+1", "'+1+1"),
        ("  =1+1", "'  =1+1"),
        (" \t-2", "' \t-2"),
        ("-2", "'-2"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tcmd", "'\tcmd"),
        ("\rcmd", "'\rcmd"),
        (chr(0xFF1D) + "1+1", "'" + chr(0xFF1D) + "1+1"),
        ("Night Ferry", "Night Ferry"),
        ("", ""),
        (None, ""),
    ],
)
def test_escape_cell(value: str | None, escaped: str) -> None:
    assert escape_cell(value) == escaped


def item(position: int, state: str, title: str, track_id: str | None = None) -> ItemRow:
    return ItemRow(
        position=position,
        source_ref=None,
        source_title=title,
        source_artist="=cmd|' /C calc'!A0",
        source_album=None,
        source_duration_ms=214000 if track_id else None,
        source_isrc=None,
        state=state,
        match_score=0.97 if track_id else None,
        yt_video_id="Wq5Jd7HsKe2" if track_id else None,
        track_id=track_id,
        error_message=None,
    )


def test_csv_report() -> None:
    track = TrackRow(
        id="t1",
        status="pending",
        title="@Night Ferry",
        artist_name="The Paper Lanterns",
        artist_id=None,
        album_name=None,
        album_id=None,
        duration_ms=None,
        year=None,
        yt_video_id="Wq5Jd7HsKe2",
        yt_album_browse_id=None,
        yt_artist_channel_id=None,
        merged_into=None,
    )
    text = csv_report(
        [item(0, "matched", "Night Ferry", "t1"), item(1, "not_found", "=1+2")], {"t1": track}
    )
    rows = list(csv.reader(io.StringIO(text)))
    assert tuple(rows[0]) == HEADER
    assert rows[1] == [
        "0",
        "matched",
        "Night Ferry",
        "'=cmd|' /C calc'!A0",
        "",
        "214",
        "",
        "0.97",
        "'@Night Ferry",
        "The Paper Lanterns",
        "Wq5Jd7HsKe2",
        "",
    ]
    assert rows[2][2] == "'=1+2"
    assert rows[2][8] == ""
