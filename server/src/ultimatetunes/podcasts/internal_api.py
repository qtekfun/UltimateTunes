# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`registerEpisode` (contracts/openapi/internal-worker.yaml). A stub until PLAN T43."""

from fastapi import APIRouter

from ultimatetunes.errors import FeatureNotImplemented

router = APIRouter()


@router.post("/internal/v1/library/episodes")
def register_episode() -> None:
    raise FeatureNotImplemented()
