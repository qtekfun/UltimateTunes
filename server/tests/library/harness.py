# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""An app with an invented library on disk, two users and the fake catalog.

`/music` (a temporary directory) holds, after `seed_files` and a scan:
- The Paper Lanterns / Harbour Lights (2023, Indie Pop, `cover.jpg` next to the files):
  `01 - Lighthouse Keeper.opus` (R128 gain) and `02 - Tidewater.mp3` (ID3, ReplayGain).
- Marisol Vega / Salt & Ember (2025, Latin Pop): `03 - Brasas.flac` with an embedded PNG.
- Files the scan skips: `notes.txt`, `clip.wav`, `.hidden.opus`.

Users: ana (`apiKey=utk_ana`) and bob (`apiKey=utk_bob`). The authenticator stands in for
PLAN T04 (tested in `tests/auth`): it maps the key to the user, or refuses with error 44.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]  # dev-only, via schemathesis
import yaml  # type: ignore[import-untyped]  # dev-only, via schemathesis
from fastapi.testclient import TestClient

from tests.conftest import CONTRACTS
from tests.library.media import JPEG, PNG, mp3_tags, write_flac, write_mp3, write_opus
from ultimatetunes.app import create_app
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.db import migrate
from ultimatetunes.errors import InvalidApiKey
from ultimatetunes.library.scan import LibraryScanner
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.settings import Settings

ANA = Principal("0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001", "ana", "user", "k-ana")
BOB = Principal("0199d6a2-4c1e-7b3a-9f10-2a6c8e01e002", "bob", "user", "k-bob")
KEYS = {"utk_ana": ANA, "utk_bob": BOB}
LIGHTHOUSE_MBID = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c01"
OPENAPI = CONTRACTS / "openapi"
_SPECS: dict[str, Any] = {}


def schema(name: str, component: str) -> jsonschema.Draft202012Validator:
    if name not in _SPECS:
        _SPECS[name] = yaml.safe_load((OPENAPI / name).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(
        {**_SPECS[name], "$ref": f"#/components/schemas/{component}"}
    )


class Keys:
    def authenticate_subsonic(
        self, params: Mapping[str, Sequence[str]], client_ip: str | None
    ) -> Principal:
        key = (params.get("apiKey") or params.get("p") or [""])[0]
        if key not in KEYS:
            raise InvalidApiKey()
        return KEYS[key]

    def authenticate_api_key(
        self, header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> Principal:
        key = header_key or query_key or ""
        if key not in KEYS:
            raise InvalidApiKey()
        return KEYS[key]


def seed_files(music: Path) -> None:
    lights = music / "The Paper Lanterns" / "Harbour Lights"
    write_opus(
        lights / "01 - Lighthouse Keeper.opus",
        {
            "title": "Lighthouse Keeper",
            "artist": "The Paper Lanterns",
            "albumartist": "The Paper Lanterns",
            "album": "Harbour Lights",
            "tracknumber": "1/2",
            "discnumber": "1",
            "date": "2023-05-01",
            "genre": "Indie Pop",
            "musicbrainz_trackid": LIGHTHOUSE_MBID,
            "r128_track_gain": "-541",
            "replaygain_track_peak": "0.988",
            "artistsort": "Paper Lanterns, The",
        },
    )
    write_mp3(
        lights / "02 - Tidewater.mp3",
        mp3_tags(
            "Tidewater",
            "The Paper Lanterns",
            "Harbour Lights",
            track="2/2",
            extra={"REPLAYGAIN_TRACK_GAIN": "-6.40 dB", "REPLAYGAIN_ALBUM_GAIN": "-6.85 dB"},
        ),
    )
    (lights / "cover.jpg").write_bytes(JPEG)
    write_flac(
        music / "Marisol Vega" / "Salt & Ember" / "03 - Brasas.flac",
        {
            "title": "Brasas",
            "artist": "Marisol Vega",
            "album": "Salt & Ember",
            "tracknumber": "3",
            "date": "2025",
            "genre": "Latin Pop",
        },
        cover=PNG,
    )
    (music / "notes.txt").write_text("not music", encoding="utf-8")
    (music / "clip.wav").write_bytes(b"RIFF")
    write_opus(music / ".hidden.opus", {"title": "Hidden"})


@dataclass
class Harness:
    services: Services
    client: TestClient
    clock: FakeClock
    catalog: FakeMusicCatalog
    music: Path

    def rest(
        self, endpoint: str, /, *, key: str = "utk_ana", fmt: str = "json", **params: Any
    ) -> Any:
        return self.client.get(f"/rest/{endpoint}", params={"f": fmt, "apiKey": key, **params})

    def ok(self, endpoint: str, component: str | None = None, /, **params: Any) -> dict[str, Any]:
        r = self.rest(endpoint, **params)
        assert r.status_code == 200, r.text
        body: dict[str, Any] = r.json()
        if component is not None:
            schema("opensubsonic-subset.yaml", component).validate(body)
        result: dict[str, Any] = body["subsonic-response"]
        assert result["status"] == "ok", result
        return result

    def error(self, endpoint: str, /, **params: Any) -> int:
        r = self.rest(endpoint, **params)
        assert r.status_code == 200, r.text
        body = r.json()["subsonic-response"]
        assert body["status"] == "failed", body
        code: int = body["error"]["code"]
        return code

    def one(self, sql: str, params: Sequence[object] = ()) -> Any:
        with self.services.db.read() as conn:
            return conn.execute(sql, params).scalar()

    def ids(self) -> dict[str, str]:
        """Title → track id, artist name → artist id, album name → album id."""
        with self.services.db.read() as conn:
            rows = conn.execute(
                "SELECT title AS k, id FROM tracks UNION ALL SELECT name AS k, id FROM artists"
                " UNION ALL SELECT name AS k, id FROM albums"
            ).fetchall()
        return {str(r["k"]): str(r["id"]) for r in rows}


def make_harness(settings: Settings, clock: FakeClock) -> Iterator[Harness]:
    conn = migrate.connect(settings.database_file)
    migrate.migrate(conn, CONTRACTS / "db" / "migrations", clock)
    conn.close()
    services = build_services(settings, clock)
    catalog = FakeMusicCatalog()
    services.catalog = catalog
    services.authenticator = Keys()
    now = format_ts(clock.now())
    with services.db.transaction() as tx:
        for user in (ANA, BOB):
            tx.execute(
                "INSERT INTO users (id, username, password_hash, role, created_at, updated_at)"
                " VALUES (?, ?, 'x', 'user', ?, ?)",
                (user.user_id, user.username, now, now),
            )
    seed_files(settings.music_dir)
    LibraryScanner(services.db, services.library, clock).scan()
    with TestClient(create_app(services=services)) as client:
        yield Harness(services, client, clock, catalog, settings.music_dir)
