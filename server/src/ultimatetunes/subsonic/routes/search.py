# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: `search3`, library merged with YouTube Music results. Owner: PLAN T06.

Library results first, then YouTube Music results with virtual ids (contracts/ids.md); plain
clients see external songs as normal songs, and playing one (`stream`) requests it. An empty
`query` lists the library (clients that sync everything) and never reaches YouTube Music.
Counts are capped at `MAX_COUNT` per kind; the query at `MAX_QUERY` characters, like
`/ut/v1/search` (longer is `InvalidParameter`, contracts/errors.md).
"""

from ultimatetunes.core.clock import format_ts
from ultimatetunes.errors import InvalidParameter, MissingParameter
from ultimatetunes.search import render
from ultimatetunes.search.service import MAX_COUNT, Page, SearchService
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()
DEFAULT_COUNT = 20
MAX_QUERY = 200


def _page(req: SubsonicRequest, kind: str) -> Page:
    count = req.get_int(f"{kind}Count", DEFAULT_COUNT)
    offset = req.get_int(f"{kind}Offset", 0)
    if count is None or offset is None or count < 0 or offset < 0:
        raise InvalidParameter(f"{kind}Count and {kind}Offset must be zero or more")
    return Page(min(count, MAX_COUNT), offset)


@router.endpoint("search3")
async def search3(req: SubsonicRequest) -> Payload:
    query = req.get("query")
    if query is None:
        raise MissingParameter("Required parameter is missing: query")
    if len(query) > MAX_QUERY:
        raise InvalidParameter(f"query must be at most {MAX_QUERY} characters")
    results = await SearchService.of(req.services).search(
        req.user.user_id,
        query,
        artists=_page(req, "artist"),
        albums=_page(req, "album"),
        songs=_page(req, "song"),
    )
    now = format_ts(req.services.clock.now())
    return {"searchResult3": render.search_result3(results, now)}
