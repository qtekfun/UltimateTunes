# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/ut/v1/search`: library merged with YouTube Music (RF-03). Owner: PLAN T06.

Routes in `router` need an API key (see `ut/__init__.py`). Library results first, then external
ones (`isExternal: true`); if YouTube Music fails or is slow, library results still come back.
`TrackItem` carries no per-user field, so this route does not need the caller's identity.
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request

from ultimatetunes.core.services import services
from ultimatetunes.search import render
from ultimatetunes.search.service import Page, SearchService

router = APIRouter()


@router.get("/ut/v1/search")
async def search(
    request: Request,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    external: bool = True,
) -> dict[str, object]:
    page = Page(limit)
    results = await SearchService.of(services(request)).search(
        None, q, artists=page, albums=page, songs=page, external=external
    )
    return render.search_result(q, results)
