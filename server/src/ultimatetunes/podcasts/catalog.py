# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the server asks YouTube Music about podcasts, and the shapes it gets back (spike T40,
docs/spikes/T40.md). PLAN T42 puts `ytmusicapi` and the guard (cache, budget, breaker) behind
this interface. Errors are those of `search/catalog.py`.

`ytmusicapi`'s `date` on show and episode pages is the view count, so no record carries it: an
exact publication time comes only from `episode_info` (or the download).
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from ultimatetunes.search.catalog import Thumbnail


@dataclass(frozen=True)
class ShowHit:
    """A show in search results. `playlist_id` is the browse id without its `MPSP` prefix."""

    playlist_id: str
    title: str
    thumbnail: Thumbnail | None = None
    author: str | None = None


@dataclass(frozen=True)
class EpisodeHit:
    """An episode in search results: no duration, no description."""

    video_id: str
    title: str
    show_id: str
    show_title: str
    published_on: date | None = None
    thumbnail: Thumbnail | None = None


@dataclass(frozen=True)
class ShowEpisode:
    """A row of a show page. `duration_s` is often precise only to the minute."""

    video_id: str
    title: str
    description: str | None = None
    duration_s: int | None = None
    thumbnail: Thumbnail | None = None


@dataclass(frozen=True)
class CatalogShow:
    playlist_id: str
    title: str
    author: str | None
    description: str | None
    thumbnail: Thumbnail | None
    episodes: tuple[ShowEpisode, ...]  # newest first


@dataclass(frozen=True)
class EpisodeInfo:
    """One episode: its show, exact length and publication time."""

    video_id: str
    show_id: str
    title: str
    description: str | None = None
    duration_s: int | None = None
    published_at: datetime | None = None
    thumbnail: Thumbnail | None = None


class PodcastCatalog(Protocol):
    async def search_shows(self, query: str, limit: int) -> list[ShowHit]: ...

    async def search_episodes(self, query: str, limit: int) -> list[EpisodeHit]: ...

    async def show(self, playlist_id: str, limit: int) -> CatalogShow:
        """The show and its newest episodes, at most `limit`."""
        ...

    async def episode_info(self, video_id: str) -> EpisodeInfo: ...
