# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The match report as CSV, safe to open in a spreadsheet (SPEC §11, T03d).

Every field comes from an uploaded file or from YouTube Music, so a cell could start with `=`,
`+`, `-`, `@`, a tab or a carriage return and run as a formula (CSV injection). `escape_cell`
prefixes such a cell with `'`, which spreadsheets show as text; the `csv` module then quotes as
needed. Numbers this module writes itself (positions, scores, durations) are not escaped.
For the admin panel (T15) and any client "export report" action.
"""

import csv
import io
from collections.abc import Mapping, Sequence

from ultimatetunes.imports.repository import ItemRow, TrackRow

# Fullwidth twins of = + - @ also start formulas in some spreadsheets.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n", *map(chr, (0xFF1D, 0xFF0B, 0xFF0D, 0xFF20)))
HEADER = (
    "position",
    "state",
    "source_title",
    "source_artist",
    "source_album",
    "source_duration_s",
    "source_isrc",
    "match_score",
    "matched_title",
    "matched_artist",
    "youtube_video_id",
    "error",
)


def escape_cell(value: str | None) -> str:
    if not value:
        return ""
    return "'" + value if value.startswith(_FORMULA_START) else value


def _number(value: float | None) -> str:
    return "" if value is None else str(value)


def csv_report(items: Sequence[ItemRow], tracks: Mapping[str, TrackRow]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(HEADER)
    for item in items:
        track = tracks.get(item.track_id) if item.track_id else None
        writer.writerow(
            (
                str(item.position),
                item.state,
                escape_cell(item.source_title),
                escape_cell(item.source_artist),
                escape_cell(item.source_album),
                _number(
                    None if item.source_duration_ms is None else item.source_duration_ms // 1000
                ),
                escape_cell(item.source_isrc),
                _number(item.match_score),
                escape_cell(track.title if track else None),
                escape_cell(track.artist_name if track else None),
                escape_cell(item.yt_video_id),
                escape_cell(item.error_message),
            )
        )
    return out.getvalue()
