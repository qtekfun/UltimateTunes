# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import fixtures: an invented catalog of 50 songs next to `FakeMusicCatalog`, a migrated
database with one user, and an app whose caller is that user. No network anywhere.

`fixtures/catalog_50.json` and `fixtures/road_trip_50.csv` were generated together (invented
names): the CSV lists 50 songs; the catalog has the first 46 (44 and 45 with a duration 20 s
off) plus an "Official Video" decoy of song 0. Rows 40-43 differ on purpose (a `feat.` in the
title, 2 s longer, other casing, no album and no duration). So 44 rows match and 6 do not.
"""

import json
import zlib
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]  # dev-only, via schemathesis
import pytest
import yaml  # type: ignore[import-untyped]  # dev-only, via schemathesis
from fastapi.testclient import TestClient

from ultimatetunes.app import create_app
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.db import Database, migrate
from ultimatetunes.search.catalog import AlbumRef, ArtistRef, CatalogTrack
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.search.text import normalize
from ultimatetunes.settings import Settings

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
USER = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001"
OTHER_USER = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01e002"
NOW = "2026-10-01T10:00:00.000Z"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def catalog_tracks() -> list[CatalogTrack]:
    records: list[dict[str, Any]] = json.loads(fixture_bytes("catalog_50.json"))
    return [
        CatalogTrack(
            video_id=r["videoId"],
            title=r["title"],
            artists=tuple(ArtistRef(a, f"UC{zlib.crc32(a.encode()):022d}") for a in r["artists"]),
            album=AlbumRef(r["album"], None) if r["album"] else None,
            duration_s=r["durationSec"],
            video_type=r["videoType"],
        )
        for r in records
    ]


class FixtureCatalog(FakeMusicCatalog):
    """`FakeMusicCatalog` plus the 50 fixture songs, with a word search like YouTube Music's:
    a song is found when every word of the query is in its title, artists or album."""

    def __init__(self) -> None:
        super().__init__()
        self.songs = catalog_tracks()
        self.tracks.update((t.video_id, t) for t in self.songs)
        self.queries: list[str] = []

    async def search_songs(self, query: str, limit: int) -> list[CatalogTrack]:
        self._call("search_songs")
        self.queries.append(query)
        words = normalize(query).split()
        found = []
        for track in [*self.songs, *self.albums_tracks()]:
            album = track.album.name if track.album else ""
            hay = set(
                normalize(" ".join([track.title, album, *(a.name for a in track.artists)])).split()
            )
            if words and all(w in hay for w in words):
                found.append(track)
        return found[:limit]

    def albums_tracks(self) -> list[CatalogTrack]:
        return [t for a in self.albums.values() for t in a.tracks]


class AllowAll:
    principal = Principal(USER, "ana", "user")

    def authenticate_subsonic(
        self, params: Mapping[str, Sequence[str]], client_ip: str | None
    ) -> Principal:
        return self.principal

    def authenticate_api_key(
        self, header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> Principal:
        return self.principal


def add_user(db: Database, user_id: str, name: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at, updated_at)"
            " VALUES (?, ?, 'x', 'user', ?, ?)",
            (user_id, name, NOW, NOW),
        )


@pytest.fixture(autouse=True)
def import_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake clock never refills the shared import bucket: give tests a large burst
    (test_runner checks the waiting with a small one)."""
    monkeypatch.setenv("UT_IMPORT_CATALOG_BURST", "1000000")


@pytest.fixture
def catalog() -> FixtureCatalog:
    return FixtureCatalog()


@pytest.fixture
def services(settings: Settings, clock: FakeClock, catalog: FixtureCatalog) -> Iterator[Services]:
    conn = migrate.connect(settings.database_file)
    migrate.migrate(conn, CONTRACTS / "db" / "migrations", clock)
    conn.close()
    svc = build_services(settings, clock)
    svc.authenticator = AllowAll()
    svc.catalog = catalog
    add_user(svc.db, USER, "ana")
    add_user(svc.db, OTHER_USER, "bea")
    yield svc
    svc.db.close()


@pytest.fixture
def client(services: Services) -> Iterator[TestClient]:
    with TestClient(create_app(services=services)) as test_client:
        yield test_client


def schema_validator(component: str) -> jsonschema.Draft202012Validator:
    spec = yaml.safe_load((CONTRACTS / "openapi" / "ut-v1.yaml").read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator({**spec, "$ref": f"#/components/schemas/{component}"})
