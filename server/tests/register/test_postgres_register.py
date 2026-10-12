# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`registerTrack` and `updateReplayGain` run unchanged on PostgreSQL (portable SQL): artist
and album lookups with and without MusicBrainz ids, reuse, merge, adoption, ReplayGain.

Runs only with UT_TEST_POSTGRES_URL (`make contracts`), in a fresh schema dropped afterwards.
"""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from tests.jobs.test_postgres_jobs import POSTGRES_URL, pg_db  # noqa: F401 - fixture
from tests.jobs.test_queue import add_track
from tests.register.test_register import AUDIO, PATH, RECORDING, body
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.storage import LocalLibraryStore, LocalStagingStore
from ultimatetunes.db import Database
from ultimatetunes.jobs.queue import SqliteJobQueue
from ultimatetunes.library.register import RegisterBody, Registrar, ReplayGainBody

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(POSTGRES_URL is None, reason="UT_TEST_POSTGRES_URL not set"),
]


class _Claim:
    def __init__(self, queue: SqliteJobQueue, staging: LocalStagingStore, track: str) -> None:
        claimed = queue.claim("w1", lease_s=60)
        assert claimed is not None
        self.job_id = claimed.job.id
        self.lease_id = claimed.lease.lease_id
        self.track_id = track
        self.staging_dir = claimed.job.staging_dir
        with staging.open_write(f"{self.staging_dir}/archive.opus") as out:
            out.write(AUDIO)


def test_register_and_replay_gain_on_postgres(
    pg_db: Database,  # noqa: F811 - the fixture
    clock: FakeClock,
    tmp_path: Path,
) -> None:
    library = LocalLibraryStore(tmp_path / "music")
    staging = LocalStagingStore(tmp_path / "staging")
    (tmp_path / "music").mkdir()
    registrar = Registrar(pg_db, clock, library, staging)
    queue = SqliteJobQueue(pg_db, clock)

    def register(c: _Claim, path: str = PATH, **meta: Any) -> dict[str, Any]:
        raw = body(c, path, **meta)  # type: ignore[arg-type]
        return registrar.register(RegisterBody.model_validate(raw)).to_contract()

    # With MusicBrainz ids, then without (the name lookups with and without an id).
    add_track(pg_db, clock, "t1", "Rb8Tn3ZcYv0")
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=100)
    c1 = _Claim(queue, staging, "t1")
    first = register(c1)
    assert first["merged"] is False
    add_track(pg_db, clock, "t2", "Qx7Lm2pZ0aB")
    queue.enqueue(track_id="t2", video_id="Qx7Lm2pZ0aB", priority=100)
    c2 = _Claim(queue, staging, "t2")
    second = register(c2, "The Paper Lanterns/Lanterns at Dusk/05 - B.opus", musicbrainz={})
    assert (second["artistId"], second["albumId"]) == (first["artistId"], first["albumId"])
    third = register(
        c2,
        "Guest/Lanterns at Dusk/05 - B.opus",
        artist="Guest",
        albumArtist="Guest",
        musicbrainz={"artistId": None, "releaseId": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c05"},
        youtube={},
    )
    assert third["artistId"] != first["artistId"]

    # The own track's ReplayGain, adoption of the moved file, then a merge.
    sha = hashlib.sha256(AUDIO).hexdigest()
    gain = ReplayGainBody.model_validate(
        {
            "jobId": c1.job_id,
            "leaseId": c1.lease_id,
            "replayGain": {"trackGainDb": -1.0, "trackPeak": 0.5, "albumGainDb": -2.0},
            "file": {"sizeBytes": len(AUDIO), "sha256": sha},
        }
    )
    registrar.replay_gain("t1", gain)
    with library.open_write(PATH) as out:
        out.write(AUDIO)
    assert register(c1)["merged"] is False
    now = format_ts(clock.now())
    with pg_db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, path,"
            " musicbrainz_recording_id, created_at, updated_at, archived_at)"
            " VALUES ('t0', 'ready', 'Old', 'old', 'X', 'A/B/old.opus', ?, ?, ?, ?)",
            (RECORDING, now, now, now),
        )
    merged = register(c1)
    assert (merged["merged"], merged["trackId"]) == (True, "t0")
    assert not library.exists(PATH)
