# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`FakeMusicCatalog`: a small invented YouTube Music (artists, albums, songs, a playlist).

Every name and id is made up (CLAUDE.md: no real data in tests or screenshots); ids follow the
formats of contracts/ids.md, and the first album matches the contract examples. Used by tests
and by the test compose stack (`UT_FAKE_YOUTUBE=true`). `calls` records every call, and
`fail_with` makes the next calls raise, for error-path tests.
"""

from ultimatetunes.errors import TunesError
from ultimatetunes.search.catalog import (
    AlbumRef,
    ArtistRef,
    CatalogAlbum,
    CatalogAlbumRef,
    CatalogArtist,
    CatalogArtistRef,
    CatalogNotFound,
    CatalogPlaylist,
    CatalogTrack,
    MoodCategory,
    Thumbnail,
)

LANTERNS = CatalogArtistRef(
    "UCq8XbV1r0LwZ5mN3tYp7kQe",
    "The Paper Lanterns",
    Thumbnail("https://yt3.googleusercontent.com/fake-paper-lanterns=w544-h544", 544, 544),
)
HARBOR = CatalogArtistRef(
    "UCn4HbR7oQ2sLx9TzV0eWm3K",
    "Neon Harbor",
    Thumbnail("https://yt3.googleusercontent.com/fake-neon-harbor=w544-h544", 544, 544),
)

_ALBUM_DATA: list[tuple[CatalogArtistRef, str, str, int, list[tuple[str, str, int]]]] = [
    (
        LANTERNS,
        "MPREb_k3Vd9QmT2xL",
        "Lanterns at Dusk",
        2024,
        [
            ("Fk2Lp9QwXa1", "Low Tide Letters", 214),
            ("Rb8Tn3ZcYv0", "Glass Orchard", 198),
            ("Wq5Jd7HsKe2", "Night Ferry", 241),
            ("Qx7Lm2pZ0aB", "Paper Moons (Live)", 262),
        ],
    ),
    (
        HARBOR,
        "MPREb_Hn2Vq8Lr5Tz",
        "Static Bloom",
        2025,
        [
            ("Hm3Vx8Nq2Lp", "Static Bloom", 187),
            ("Tz9Kd4Wb7Rc", "Signal Fires", 225),
            ("Pa6Ye1Uo3Gs", "Harbor Lights", 203),
        ],
    ),
]


def _build() -> tuple[dict[str, CatalogAlbum], dict[str, CatalogTrack]]:
    albums: dict[str, CatalogAlbum] = {}
    tracks: dict[str, CatalogTrack] = {}
    for artist, browse_id, title, year, songs in _ALBUM_DATA:
        artists = (ArtistRef(artist.name, artist.channel_id),)
        thumb = Thumbnail(f"https://i.ytimg.com/vi/{songs[0][0]}/hqdefault.jpg", 480, 360)
        ref = CatalogAlbumRef(browse_id, title, artists, year, thumb)
        album_tracks = tuple(
            CatalogTrack(
                video_id=video_id,
                title=song,
                artists=artists,
                album=AlbumRef(title, browse_id),
                duration_s=duration,
                video_type="ATV",
                year=year,
                track_number=number,
                thumbnail=Thumbnail(f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg", 480, 360),
            )
            for number, (video_id, song, duration) in enumerate(songs, start=1)
        )
        albums[browse_id] = CatalogAlbum(ref, album_tracks, "album")
        tracks.update((t.video_id, t) for t in album_tracks)
    return albums, tracks


PLAYLIST_ID = "PLfakeRoadTrip0123456789abcdefGH"
# Invented "Moods & genres" categories (ids follow the opaque base64url shape of the real ones).
MOODS = (
    MoodCategory("ggFAKEchill0000000000000", "Chill"),
    MoodCategory("ggFAKEfocus0000000000000", "Focus"),
)


class FakeMusicCatalog:
    def __init__(self) -> None:
        self.albums, self.tracks = _build()
        self.artists = {a.channel_id: a for a in (LANTERNS, HARBOR)}
        self.calls: list[str] = []
        self.fail_with: TunesError | None = None

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_with is not None:
            raise self.fail_with

    @staticmethod
    def _match(query: str, *fields: str | None) -> bool:
        needle = query.strip().casefold()
        return bool(needle) and any(needle in (f or "").casefold() for f in fields)

    async def search_songs(self, query: str, limit: int) -> list[CatalogTrack]:
        self._call("search_songs")
        found = [
            t
            for t in self.tracks.values()
            if self._match(query, t.title, t.artists[0].name, t.album.name if t.album else None)
        ]
        return found[:limit]

    async def search_albums(self, query: str, limit: int) -> list[CatalogAlbumRef]:
        self._call("search_albums")
        found = [
            a.ref
            for a in self.albums.values()
            if self._match(query, a.ref.title, a.ref.artists[0].name)
        ]
        return found[:limit]

    async def search_artists(self, query: str, limit: int) -> list[CatalogArtistRef]:
        self._call("search_artists")
        return [a for a in self.artists.values() if self._match(query, a.name)][:limit]

    async def album(self, browse_id: str) -> CatalogAlbum:
        self._call("album")
        try:
            return self.albums[browse_id]
        except KeyError:
            raise CatalogNotFound() from None

    async def artist(self, channel_id: str) -> CatalogArtist:
        self._call("artist")
        ref = self.artists.get(channel_id)
        if ref is None:
            raise CatalogNotFound()
        albums = tuple(a for a in self.albums.values() if a.ref.artists[0].channel_id == channel_id)
        top = tuple(t for a in albums for t in a.tracks)
        return CatalogArtist(ref, top, tuple(a.ref for a in albums))

    async def track(self, video_id: str) -> CatalogTrack:
        self._call("track")
        try:
            return self.tracks[video_id]
        except KeyError:
            raise CatalogNotFound() from None

    async def radio(self, video_id: str, limit: int) -> list[CatalogTrack]:
        self._call("radio")
        seed = self.tracks.get(video_id)
        if seed is None:
            raise CatalogNotFound()
        others = [t for t in self.tracks.values() if t.video_id != video_id]
        return [seed, *others][:limit]

    async def playlist(self, playlist_id: str) -> CatalogPlaylist:
        self._call("playlist")
        if playlist_id != PLAYLIST_ID:
            raise CatalogNotFound()
        picks = ("Wq5Jd7HsKe2", "Tz9Kd4Wb7Rc", "Qx7Lm2pZ0aB")
        return CatalogPlaylist(
            PLAYLIST_ID, "Road Trip (fake)", tuple(self.tracks[v] for v in picks), 1
        )

    async def charts(self, country: str) -> list[CatalogTrack]:
        self._call("charts")
        # A deterministic "top chart" for every country: the catalog's songs in order.
        return list(self.tracks.values())

    async def moods(self) -> list[MoodCategory]:
        self._call("moods")
        return list(MOODS)

    async def mood_tracks(self, params: str) -> list[CatalogTrack]:
        self._call("mood_tracks")
        picks = {
            MOODS[0].params: ("Fk2Lp9QwXa1", "Rb8Tn3ZcYv0"),
            MOODS[1].params: ("Hm3Vx8Nq2Lp", "Tz9Kd4Wb7Rc", "Pa6Ye1Uo3Gs"),
        }.get(params, ())
        return [self.tracks[v] for v in picks]
