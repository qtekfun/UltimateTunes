# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""FakePodcastCatalog: the shapes spike T40 saw, in the id formats of contracts/ids.md."""

import re

import pytest

from ultimatetunes.errors import NotFound, UpstreamUnavailable
from ultimatetunes.podcasts.catalog import PodcastCatalog
from ultimatetunes.podcasts.fake import SHOW_ID, SLACK_WATER, FakePodcastCatalog
from ultimatetunes.search.catalog import CatalogUnavailable

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_search_show_and_episode() -> None:
    catalog: PodcastCatalog = FakePodcastCatalog()
    [show] = await catalog.search_shows("tide", 5)
    assert show.playlist_id == SHOW_ID
    assert show.author is None
    hits = await catalog.search_episodes("tide", 2)
    assert len(hits) == 2
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{11}", h.video_id) for h in hits)
    assert hits[1].published_on is None
    assert await catalog.search_shows(" ", 5) == []
    page = await catalog.show(SHOW_ID, 2)
    assert [e.title for e in page.episodes] == ["Slack water", "The night pilot"]
    info = await catalog.episode_info(SLACK_WATER)
    assert (info.show_id, info.duration_s) == (SHOW_ID, 4381)
    assert info.published_at is not None


async def test_unknown_ids_and_failures() -> None:
    catalog = FakePodcastCatalog()
    with pytest.raises(NotFound):
        await catalog.show("PLnothing", 20)
    with pytest.raises(NotFound):
        await catalog.episode_info("AAAAAAAAAAA")
    catalog.fail_with = CatalogUnavailable()
    with pytest.raises(UpstreamUnavailable):
        await catalog.search_shows("tide", 5)
    assert catalog.calls == ["show", "episode_info", "search_shows"]
