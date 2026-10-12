<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ytmusicapi response fixtures

Decoded ytmusicapi 1.12.3 responses in the shapes recorded by spike T03b
(`docs/spikes/T03b.md`, "Fixture guidance"), trimmed the same way (no feedback tokens, one
thumbnail size where the shape allows). Names, ids and URLs are **invented** (CLAUDE.md: no
real data in tests), in the real id formats. Each file adds the edge cases seen in the spike:
artists without a channel id, unavailable entries, non-song items in results, the `gstatic`
placeholder avatar, and string vs integer years.

| File | Call |
| --- | --- |
| `search_songs.json` | `search(q, filter="songs")` |
| `search_albums.json` | `search(q, filter="albums")` |
| `search_artists.json` | `search(q, filter="artists")` |
| `album.json` | `get_album("MPREb_k3Vd9QmT2xL")` |
| `artist.json` | `get_artist("UCq8XbV1r0LwZ5mN3tYp7kQe")` |
| `watch_playlist.json` | `get_watch_playlist(videoId="Fk2Lp9QwXa1", radio=True)` |
| `playlist.json` | `get_playlist("PLfakeRoadTrip0123456789abcdefGH", limit=None)` |
