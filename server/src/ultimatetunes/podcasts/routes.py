# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/ut/v1/podcasts` (contracts/openapi/ut-v1.yaml). Stubs until PLAN T42 to T44."""

from fastapi import APIRouter

from ultimatetunes.errors import FeatureNotImplemented

router = APIRouter(prefix="/ut/v1/podcasts")


def _stub() -> None:
    raise FeatureNotImplemented()


for _method, _path in (
    ("GET", "/search"),
    ("GET", "/shows"),
    ("GET", "/shows/{show_id}"),
    ("GET", "/shows/{show_id}/episodes"),
    ("PUT", "/shows/{show_id}/follow"),
    ("DELETE", "/shows/{show_id}/follow"),
    ("GET", "/new"),
    ("GET", "/continue"),
    ("GET", "/episodes/{episode_id}"),
    ("POST", "/episodes/{episode_id}/request"),
    ("GET", "/progress"),
    ("PUT", "/progress"),
):
    router.add_api_route(_path, _stub, methods=[_method])
