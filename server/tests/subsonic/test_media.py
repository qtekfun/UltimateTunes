# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`stream` and `download` of library files: Range, HEAD, errors and the T16 seam."""

from typing import Any

import pytest
from starlette.responses import Response

from tests.library.harness import Harness
from ultimatetunes.ids.resolve import TrackRef
from ultimatetunes.ids.virtual import VirtualId
from ultimatetunes.library.stream import RangeNotSatisfiableError, attachment, parse_range

LIGHTHOUSE = "The Paper Lanterns/Harbour Lights/01 - Lighthouse Keeper.opus"


def file_bytes(lib: Harness, rel: str) -> bytes:
    return (lib.music / rel).read_bytes()


def stream(lib: Harness, song: str, *, name: str = "stream", **headers: str) -> Any:
    return lib.client.get(
        f"/rest/{name}", params={"apiKey": "utk_ana", "id": song}, headers=headers
    )


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        (None, 10, None),
        ("", 10, None),
        ("bytes=0-3", 10, (0, 3)),
        ("bytes=4-", 10, (4, 9)),
        ("bytes=-3", 10, (7, 9)),
        ("bytes=-30", 10, (0, 9)),
        ("bytes=2-100", 10, (2, 9)),
        ("bytes=5-2", 10, None),
        ("bytes=-", 10, None),
        ("bytes=0-1,4-5", 10, None),
        ("items=0-1", 10, None),
        # Audit L1: only ASCII digits, at most 19 of them; anything else is no range.
        ("bytes=0-" + "9" * 19, 10, (0, 9)),
        ("bytes=" + "1" * 20 + "-", 10, None),
        ("bytes=0-" + "9" * 5000, 10, None),
        ("bytes=-" + "9" * 5000, 10, None),
        ("bytes=\u0661-", 10, None),
    ],
)
def test_parse_range(header: str | None, size: int, expected: tuple[int, int] | None) -> None:
    found = parse_range(header, size)
    assert (None if found is None else (found.start, found.end)) == expected


@pytest.mark.parametrize(("header", "size"), [("bytes=10-", 10), ("bytes=-0", 10), ("bytes=-5", 0)])
def test_parse_range_unsatisfiable(header: str, size: int) -> None:
    with pytest.raises(RangeNotSatisfiableError):
        parse_range(header, size)


def test_attachment_name() -> None:
    assert attachment("01 - Café.opus") == (
        "attachment; filename=\"01 - Caf_.opus\"; filename*=UTF-8''01%20-%20Caf%C3%A9.opus"
    )


def test_stream_whole_file(lib: Harness) -> None:
    song = lib.ids()["Lighthouse Keeper"]
    data = file_bytes(lib, LIGHTHOUSE)
    r = stream(lib, song)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/ogg"
    assert r.headers["accept-ranges"] == "bytes"
    assert int(r.headers["content-length"]) == len(data)
    assert r.content == data
    assert "content-disposition" not in r.headers


def test_a_huge_range_is_ignored_without_an_error(
    lib: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    """Audit L1: thousands of digits used to reach `int()` and log a traceback."""
    song = lib.ids()["Lighthouse Keeper"]
    data = file_bytes(lib, LIGHTHOUSE)
    r = stream(lib, song, Range="bytes=0-" + "9" * 5000)
    assert r.status_code == 200
    assert r.content == data
    assert not [rec for rec in caplog.records if rec.exc_info]


def test_stream_ranges(lib: Harness) -> None:
    song = lib.ids()["Lighthouse Keeper"]
    data = file_bytes(lib, LIGHTHOUSE)
    r = stream(lib, song, Range="bytes=10-99")
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 10-99/{len(data)}"
    assert r.headers["content-length"] == "90"
    assert r.content == data[10:100]
    tail = stream(lib, song, Range="bytes=-16")
    assert tail.status_code == 206
    assert tail.content == data[-16:]
    past = stream(lib, song, Range=f"bytes={len(data)}-")
    assert past.status_code == 416
    assert past.headers["content-range"] == f"bytes */{len(data)}"
    assert past.content == b""


def test_head_has_the_headers_and_no_body(lib: Harness) -> None:
    song = lib.ids()["Tidewater"]
    r = lib.client.head("/rest/stream", params={"apiKey": "utk_ana", "id": song})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert int(r.headers["content-length"]) > 0
    assert r.content == b""


def test_download_is_an_attachment(lib: Harness) -> None:
    song = lib.ids()["Brasas"]
    r = stream(lib, song, name="download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/flac"
    assert r.headers["content-disposition"].startswith('attachment; filename="03 - Brasas.flac"')
    r = lib.client.post(
        "/rest/download.view",
        data={"apiKey": "utk_ana", "id": song},
        headers={"Range": "bytes=0-3"},
    )
    assert r.status_code == 206
    assert r.content == b"fLaC"


def test_stream_errors(lib: Harness) -> None:
    assert lib.error("stream", id="0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff") == 70
    assert lib.error("stream", id="ytalbum:MPREb_k3Vd9QmT2xL") == 70
    assert lib.error("stream", id="../../etc/passwd") == 70
    assert lib.error("stream") == 10
    r = lib.client.get("/rest/stream", params={"apiKey": "utk_ana", "id": "x", "f": "xml"})
    assert '<error code="70"' in r.text
    # A ready track whose file disappeared.
    (lib.music / LIGHTHOUSE).unlink()
    assert lib.error("stream", id=lib.ids()["Lighthouse Keeper"]) == 70


def test_failed_download_is_404(lib: Harness) -> None:
    song = lib.ids()["Brasas"]
    with lib.services.db.transaction() as conn:
        conn.execute("UPDATE tracks SET status = 'failed' WHERE id = ?", (song,))
    r = stream(lib, song)
    assert r.status_code == 404
    assert '<error code="70"' in r.text
    r = lib.client.get("/rest/stream", params={"apiKey": "utk_ana", "id": song, "f": "json"})
    assert r.status_code == 404
    assert r.json()["subsonic-response"]["error"]["code"] == 70


def test_yt_alias_of_an_archived_song_streams_the_file(lib: Harness) -> None:
    song = lib.ids()["Lighthouse Keeper"]
    with lib.services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO track_aliases (alias, track_id, created_at) VALUES (?, ?, ?)",
            ("yt:Wq5Jd7HsKe2", song, "2026-10-12T08:00:00.000Z"),
        )
    r = stream(lib, "yt:Wq5Jd7HsKe2")
    assert r.status_code == 200
    assert r.content == file_bytes(lib, LIGHTHOUSE)


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str | None, bool, bool]] = []

    async def serve(
        self,
        req: object,
        target: TrackRef | VirtualId,
        *,
        video: str | None,
        download: bool,
        head: bool,
    ) -> Response:
        self.calls.append((target, video, download, head))
        return Response(b"growing", media_type="audio/webm")


def test_songs_without_a_file_go_to_the_streaming_seam(lib: Harness) -> None:
    recorder = Recorder()
    lib.client.app.state.pending_streams = recorder  # type: ignore[attr-defined]
    assert stream(lib, "yt:Qx7Lm2pZ0aB").content == b"growing"
    head = lib.client.head("/rest/download", params={"apiKey": "utk_ana", "id": "yt:Qx7Lm2pZ0aB"})
    assert head.content == b""
    with lib.services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, yt_video_id,"
            " created_at, updated_at) VALUES (?, 'pending', 'P', 'p', 'A', 'Rb8Tn3ZcYv0', ?, ?)",
            (
                "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0aa",
                "2026-10-12T08:00:00.000Z",
                "2026-10-12T08:00:00.000Z",
            ),
        )
    stream(lib, "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0aa")
    assert recorder.calls == [
        (VirtualId("song", "Qx7Lm2pZ0aB"), "Qx7Lm2pZ0aB", False, False),
        (VirtualId("song", "Qx7Lm2pZ0aB"), "Qx7Lm2pZ0aB", True, True),
        (TrackRef("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0aa", "pending"), "Rb8Tn3ZcYv0", False, False),
    ]
    # Streaming never materializes anything by itself here (that is the seam's job).
    assert lib.one("SELECT COUNT(*) FROM track_aliases") == 0
