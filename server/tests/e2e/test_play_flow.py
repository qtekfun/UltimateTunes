# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Search → play an external song → streamed while it downloads → archived → replayed from disk.

The whole play flow of SPEC section 3 on the real containers: the api, the worker with the fake
downloader (the bundled silent Ogg/Opus, written slowly) and the real tagging and archive steps
(MusicBrainz and Cover Art Archive are off on the test stack). The offline replay from the
phone's cache is the device half (`android/app/src/androidTest/.../e2e`).
"""

import io
from typing import Any

import pytest
from mutagen.oggopus import OggOpus

from tests.e2e.conftest import UserFactory
from ultimatetunes.worker.fake import silence_opus

pytestmark = pytest.mark.e2e

VIDEO = "Fk2Lp9QwXa1"
SONG = f"yt:{VIDEO}"
TITLE, ARTIST, ALBUM = "Low Tide Letters", "The Paper Lanterns", "Lanterns at Dusk"


def test_search_play_stream_archive_replay(make_user: UserFactory) -> None:
    user = make_user("carol")
    audio = silence_opus()

    # Search: the song is only on (fake) YouTube Music, marked external and never requested.
    found = [t for t in user.search_tracks("Low Tide") if t["id"] == SONG]
    assert len(found) == 1
    assert found[0]["isExternal"] is True
    assert found[0]["libraryState"] is None
    assert user.status(SONG)["state"] == "not_requested"

    # Play: the first `stream` starts the download and sends the bytes as the worker writes them.
    with user.stream(SONG) as answer:
        assert answer.status_code == 200
        assert answer.headers["content-length"] == str(len(audio))
        assert answer.headers["accept-ranges"] == "bytes"
        assert answer.headers["cache-control"] == "no-store"
        chunks = answer.iter_bytes()
        received = next(chunks)
        assert 0 < len(received) < len(audio)
        # The first bytes arrived while the worker is still downloading.
        during = user.status(SONG)
        assert during["state"] == "downloading", during
        assert during["streamable"] is True
        assert 0 < during["progress"] < 1
        for chunk in chunks:
            received += chunk
    assert received == audio

    # Archived: tagged, moved into the library, the `yt:` id now an alias of the library song.
    ready = user.wait_ready(SONG)
    track_id = ready["trackId"]
    assert ready["attempts"] == 1
    song = user.rest("getSong", id=track_id)["song"]
    assert (song["title"], song["artist"], song["album"]) == (TITLE, ARTIST, ALBUM)
    assert song["suffix"] == "opus"
    assert song["path"] == f"{ARTIST}/{ALBUM}/01 - {TITLE}.opus"
    again = [t for t in user.search_tracks("Low Tide") if t["title"] == TITLE]
    assert [(t["id"], t["isExternal"], t["libraryState"]) for t in again] == [
        (track_id, False, "ready")
    ]

    # Replay: from the library file now, with ranges, tags and ReplayGain written by the worker.
    with user.stream(track_id) as answer:
        assert answer.status_code == 200
        assert answer.headers["accept-ranges"] == "bytes"
        archived = answer.read()
    assert archived != audio  # remuxed and tagged, never the raw download
    tags: Any = OggOpus(io.BytesIO(archived))  # type: ignore[no-untyped-call]
    assert tags["title"] == [TITLE]
    assert tags["artist"] == [ARTIST]
    assert tags["album"] == [ALBUM]
    assert "REPLAYGAIN_TRACK_GAIN" in tags
    assert "R128_TRACK_GAIN" in tags
    with user.stream(track_id, {"Range": "bytes=0-99"}) as answer:
        assert answer.status_code == 206
        assert answer.headers["content-range"] == f"bytes 0-99/{len(archived)}"
        assert answer.read() == archived[:100]
    # The old `yt:` id plays the same library file.
    with user.stream(SONG) as answer:
        assert answer.status_code == 200
        assert answer.read() == archived
