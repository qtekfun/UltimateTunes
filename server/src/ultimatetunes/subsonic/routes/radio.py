# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: `getSimilarSongs2`, the radio of a song or an artist. Owner: PLAN T07.

Same source as `/ut/v1/radio` (`radio.service`), local-first: archived songs come with their
library ids, the others with `yt:` ids (plain clients play them like any song). The songs are
*similar* ones, so a song seed is left out; for an artist seed the list starts with the
artist's top song. `count` (default 50) is capped at `MAX_RADIO`.
"""

from ultimatetunes.errors import InvalidParameter
from ultimatetunes.radio.service import MAX_RADIO, RadioService
from ultimatetunes.search import render
from ultimatetunes.search.service import Song
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()
DEFAULT_COUNT = 50


@router.endpoint("getSimilarSongs2")
async def get_similar_songs2(req: SubsonicRequest) -> Payload:
    seed_id = req.require("id")
    count = req.get_int("count", DEFAULT_COUNT)
    if count is None or count < 0:
        raise InvalidParameter("count must be zero or more")
    count = min(count, MAX_RADIO)
    radio = await RadioService.of(req.services).radio(
        req.user.user_id, seed_id, max(count, 1), artists=True
    )
    songs: list[Song] = [radio.seed] if radio.from_artist else []
    songs = [*songs, *radio.items][:count]
    return {"similarSongs2": {"song": [render.child(s) for s in songs]}}
