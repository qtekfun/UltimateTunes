# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`LibraryStore` (`/music`) and `StagingStore` (`/staging`): the only way to touch files.

Paths are POSIX strings **relative** to the store root (as in the internal worker API). Every
call checks them before touching the disk and raises `PathRejected` when a path is absolute,
not normalized (`.`/`..` segments, empty segments, backslashes, NUL) or resolves outside the
root (also through a symlink). This is the floor, not the path sanitizer: T09 builds names
from metadata in `paths/` and they still go through these checks.

v1 implements both on the local filesystem; a shared volume needs nothing else, and an
S3-compatible store (phase 5) would implement the same protocols.
"""

import os
import secrets
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol

from ultimatetunes.errors import Conflict, PathRejected

MAX_PATH_LENGTH = 1024


@dataclass(frozen=True)
class Usage:
    total_bytes: int
    used_bytes: int
    free_bytes: int


class FileStore(Protocol):
    def check(self, rel: str) -> str:
        """Returns `rel` when it is a valid relative path inside the store, else raises."""
        ...

    def exists(self, rel: str) -> bool: ...

    def size(self, rel: str) -> int: ...

    def open_read(self, rel: str) -> BinaryIO: ...

    def open_write(self, rel: str, *, append: bool = False) -> BinaryIO:
        """Creates parent directories as needed."""
        ...

    def rename(self, src: str, dst: str) -> None:
        """Atomic rename inside the store (replaces `dst`)."""
        ...

    def delete(self, rel: str) -> None:
        """Deletes a file or a whole directory. Missing paths are fine."""
        ...

    def local_path(self, rel: str) -> Path:
        """Filesystem path, for subprocesses that need one (yt-dlp, ffmpeg). Checked too."""
        ...

    def is_writable(self) -> bool: ...

    def usage(self) -> Usage: ...


class StagingStore(FileStore, Protocol):
    """Partial downloads, one directory per job (`<jobId>/`). Shared by api and worker."""


class LibraryStore(FileStore, Protocol):
    """The archived library."""

    def import_file(self, staging: StagingStore, src: str, dst: str) -> None:
        """Copies a finished staging file into the library atomically (temp file in the target
        directory, fsync, rename). Refuses to overwrite an existing file (`Conflict`)."""
        ...


def check_relative(rel: str) -> str:
    """Syntactic checks shared by every store."""
    if not rel or len(rel) > MAX_PATH_LENGTH:
        raise PathRejected("path is empty or too long")
    if "\x00" in rel or "\\" in rel:
        raise PathRejected("path contains NUL or a backslash")
    if rel.startswith("/"):
        raise PathRejected("path must be relative")
    parts = rel.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PathRejected("path is not normalized")
    return str(PurePosixPath(rel))


class LocalStore:
    """A `FileStore` on a local directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def check(self, rel: str) -> str:
        return check_relative(rel)

    def local_path(self, rel: str) -> Path:
        clean = check_relative(rel)
        root = self.root.resolve()
        path = (root / clean).resolve()
        if not path.is_relative_to(root) or path == root:
            raise PathRejected("path escapes the store")
        return path

    def exists(self, rel: str) -> bool:
        return self.local_path(rel).exists()

    def size(self, rel: str) -> int:
        return self.local_path(rel).stat().st_size

    def open_read(self, rel: str) -> BinaryIO:
        return self.local_path(rel).open("rb")

    def open_write(self, rel: str, *, append: bool = False) -> BinaryIO:
        path = self.local_path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open("ab" if append else "wb")

    def rename(self, src: str, dst: str) -> None:
        target = self.local_path(dst)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.local_path(src).replace(target)

    def delete(self, rel: str) -> None:
        path = self.local_path(rel)
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

    def is_writable(self) -> bool:
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".probe-"):
                pass
        except OSError:
            return False
        return True

    def usage(self) -> Usage:
        total, used, free = shutil.disk_usage(self.root)
        return Usage(total, used, free)


class LocalStagingStore(LocalStore):
    """`StagingStore` on `/staging`."""


class LocalLibraryStore(LocalStore):
    """`LibraryStore` on `/music`."""

    def import_file(self, staging: StagingStore, src: str, dst: str) -> None:
        target = self.local_path(dst)
        if target.exists():
            raise Conflict(f"a file already exists at {dst}")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
        try:
            with staging.open_read(src) as reader, tmp.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
                writer.flush()
                os.fsync(writer.fileno())
            # A hard link appears atomically and fails if the target exists (no overwrite).
            os.link(tmp, target)
        except FileExistsError as exc:
            raise Conflict(f"a file already exists at {dst}") from exc
        finally:
            tmp.unlink(missing_ok=True)
