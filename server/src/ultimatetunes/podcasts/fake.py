# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`FakePodcastCatalog`: invented shows in the shapes of spike T40, matching the contract
examples. `calls` records every call and `fail_with` makes the next calls raise.
"""

from datetime import UTC, date, datetime

from ultimatetunes.errors import TunesError
from ultimatetunes.podcasts.catalog import (
    CatalogShow,
    EpisodeHit,
    EpisodeInfo,
    ShowEpisode,
    ShowHit,
)
from ultimatetunes.search.catalog import CatalogNotFound, Thumbnail

SHOW_ID = "PLfakeTideTables0123456789abcdef"
SLACK_WATER = "Pd4Kx9Lm2Qa"
NIGHT_PILOT = "Pd7Wn3Rt8Vb"
FOG_SIGNALS = "Pd1Zc5Hy6Js"


def _thumbnail(video_id: str) -> Thumbnail:
    return Thumbnail(f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg", 480, 360)


_EPISODES = (
    ShowEpisode(
        SLACK_WATER,
        "Slack water",
        "How a harbour keeps time.\n\n0:00 Welcome\n4:30 Reading a tide table\n"
        "31:05 Listener letters",
        4380,
        _thumbnail(SLACK_WATER),
    ),
    ShowEpisode(NIGHT_PILOT, "The night pilot", "A night on the pilot boat.", 1620),
    ShowEpisode(FOG_SIGNALS, "Fog signals"),
)
_SHOW = CatalogShow(
    SHOW_ID,
    "Tide Tables",
    "Harbour Radio Club",
    "An invented show about harbours.",
    Thumbnail("https://yt3.googleusercontent.com/fake-tide-tables=w544-h544", 544, 544),
    _EPISODES,
)
# Exact values only `episode_info` knows. The last episode has no publication time.
_EXACT = {
    SLACK_WATER: (4381, datetime(2026, 11, 26, 5, 0, tzinfo=UTC)),
    NIGHT_PILOT: (1634, datetime(2026, 11, 19, 5, 0, tzinfo=UTC)),
    FOG_SIGNALS: (2040, None),
}


class FakePodcastCatalog:
    def __init__(self) -> None:
        self.shows = {SHOW_ID: _SHOW}
        self.calls: list[str] = []
        self.fail_with: TunesError | None = None

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_with is not None:
            raise self.fail_with

    @staticmethod
    def _match(query: str, *fields: str | None) -> bool:
        needle = query.strip().casefold()
        return bool(needle) and any(needle in (f or "").casefold() for f in fields)

    async def search_shows(self, query: str, limit: int) -> list[ShowHit]:
        self._call("search_shows")
        # Like the real search: no author on a show hit.
        return [
            ShowHit(s.playlist_id, s.title, s.thumbnail)
            for s in self.shows.values()
            if self._match(query, s.title, s.author)
        ][:limit]

    async def search_episodes(self, query: str, limit: int) -> list[EpisodeHit]:
        self._call("search_episodes")
        return [
            EpisodeHit(
                e.video_id,
                e.title,
                s.playlist_id,
                s.title,
                date(2026, 11, 26) if e.video_id == SLACK_WATER else None,
                e.thumbnail,
            )
            for s in self.shows.values()
            for e in s.episodes
            if self._match(query, e.title, s.title)
        ][:limit]

    async def show(self, playlist_id: str, limit: int) -> CatalogShow:
        self._call("show")
        found = self.shows.get(playlist_id)
        if found is None:
            raise CatalogNotFound()
        return CatalogShow(
            found.playlist_id,
            found.title,
            found.author,
            found.description,
            found.thumbnail,
            found.episodes[:limit],
        )

    async def episode_info(self, video_id: str) -> EpisodeInfo:
        self._call("episode_info")
        for show in self.shows.values():
            for episode in show.episodes:
                if episode.video_id == video_id:
                    duration, published = _EXACT[video_id]
                    return EpisodeInfo(
                        video_id,
                        show.playlist_id,
                        episode.title,
                        episode.description,
                        duration,
                        published,
                        episode.thumbnail,
                    )
        raise CatalogNotFound()
