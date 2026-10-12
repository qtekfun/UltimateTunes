# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`Archiver`: what happens between a finished download and `complete` (PLAN T09).

The loop downloads, reports `tagging`, then hands the attempt to the archiver, still holding
the lease (heartbeats keep running). The archiver builds the tagged archive file in the
attempt's staging directory (remux, tags, ReplayGain), calls `registerTrack` through the
`WorkerApi`, moves the file into `/music` when register reserved the path, and returns
the `Archived` decision; the loop then calls `complete` with it. An `ArchiveError`-style
failure is a `DownloadError` (e.g. `tagging_failed`, `storage_error`).

T09 implements this protocol in `ultimatetunes.tagging` (`TaggingArchiver`), which
`default_archiver` builds for `loop.build_worker`. `PendingArchiver` fails the job (not
retried); it stays for tests of the loop.
"""

from dataclasses import dataclass
from typing import Protocol

from ultimatetunes.core.storage import LibraryStore, StagingStore
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.settings import Settings
from ultimatetunes.worker.client import ClaimedJob, WorkerApi
from ultimatetunes.worker.downloader import DownloadError, DownloadResult


@dataclass(frozen=True)
class ArchiveRequest:
    job: ClaimedJob
    download: DownloadResult
    api: WorkerApi
    staging: StagingStore
    library: LibraryStore


@dataclass(frozen=True)
class Archived:
    """The `complete` call to make: `library_path` None when register answered merged."""

    track_id: str
    library_path: str | None


class Archiver(Protocol):
    async def archive(self, request: ArchiveRequest) -> Archived: ...


class PendingArchiver:
    """Placeholder until T09's archiver is wired in `loop.build_worker`."""

    async def archive(self, request: ArchiveRequest) -> Archived:
        raise DownloadError(
            WorkerErrorCode.TAGGING_FAILED, "archiving is not available yet", retryable=False
        )


def default_archiver(settings: Settings) -> Archiver:
    """The production archiver (PLAN T09). Imported here, not at the top: `tagging` builds on
    this module's records."""
    from ultimatetunes.tagging.archiver import build_archiver  # noqa: PLC0415

    return build_archiver(settings)
