# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: Synced and plain lyrics (SPEC RF-07). Owner: PLAN T10.

`getLyricsBySongId` (`songLyrics` extension, version 1): `id` is a library UUID or a `yt:` id
(contracts/ids.md); `enhanced` is ignored. The lookup itself is `lyrics.service`.
"""

from ultimatetunes.lyrics.service import build_lyrics_service
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()


@router.endpoint("getLyricsBySongId")
def get_lyrics_by_song_id(req: SubsonicRequest) -> Payload:
    song_id = req.require("id")
    lyrics = build_lyrics_service(req.services).structured_lyrics(song_id)
    return {"lyricsList": {"structuredLyrics": lyrics}}
