# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: the saved play queue (RF-09). Owner: PLAN T05.

`savePlayQueue` stores raw ids and never starts a download; `getPlayQueue` resolves them
(`library.playqueue`). `changedBy` is the client name (`c`). Without a saved queue the
envelope has no `playQueue`.
"""

from starlette.concurrency import run_in_threadpool

from ultimatetunes.library.playqueue import PlayQueue
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()


def _queue(req: SubsonicRequest) -> PlayQueue:
    return PlayQueue(req.services, req.user.user_id, req.user.username)


@router.endpoint("getPlayQueue")
async def get_play_queue(req: SubsonicRequest) -> Payload:
    queue = await _queue(req).get()
    return {} if queue is None else {"playQueue": queue}


@router.endpoint("savePlayQueue")
async def save_play_queue(req: SubsonicRequest) -> Payload:
    await run_in_threadpool(
        lambda: _queue(req).save(
            req.get_all("id"),
            current=req.get("current") or None,
            position_ms=req.get_int("position", 0) or 0,
            client=req.get("c"),
        )
    )
    return {}
