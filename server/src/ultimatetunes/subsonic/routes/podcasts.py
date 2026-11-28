# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The OpenSubsonic podcast endpoints. Stubs until PLAN T42 to T44."""

from ultimatetunes.errors import FeatureNotImplemented
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()


def _stub(_req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


for _name in (
    "getPodcasts",
    "getNewestPodcasts",
    "getPodcastEpisode",
    "createPodcastChannel",
    "deletePodcastChannel",
    "downloadPodcastEpisode",
    "deletePodcastEpisode",
    "refreshPodcasts",
):
    router.endpoint(_name)(_stub)
