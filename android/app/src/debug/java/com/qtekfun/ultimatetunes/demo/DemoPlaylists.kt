// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.demo

import com.qtekfun.ultimatetunes.core.api.model.CoverArtId
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.Song
import java.time.Instant

/** The demo's playlists: a few invented mixes over [DemoCatalog]. */
internal object DemoPlaylists {
    fun newId(n: Int): String = "0199e0de-0004-7000-8000-%012x".format(n)

    fun of(
        id: PlaylistId,
        name: String,
        songs: List<Song>,
        at: Instant,
        comment: String? = null
    ): Playlist = Playlist(
        id = id,
        name = name,
        comment = comment,
        owner = "demo",
        public = false,
        songCount = songs.size,
        duration = songs.sumOf { it.duration ?: 0 },
        created = at,
        changed = at,
        // Like the server: the playlist shows the cover of its first song.
        coverArt = songs.firstOrNull()?.coverArt ?: CoverArtId("pl-${id.value}"),
        readonly = false,
        entry = songs
    )

    fun initial(at: Instant): List<Playlist> {
        val songs = DemoCatalog.songs
        return listOf(
            Triple("Morning Coffee", "Gentle songs to start the day", setOf("Folk", "Jazz")),
            Triple(
                "Late Night Drive",
                "Neon, bass and empty roads",
                setOf("Synth-pop", "Electronic")
            ),
            Triple(
                "Sunday Garden",
                "Warm guitars and open windows",
                setOf("Pop", "Dream pop", "Rock")
            )
        ).mapIndexed { i, (name, comment, genres) ->
            of(
                id = PlaylistId(newId(i + 1)),
                name = name,
                songs = songs.filter {
                    it.genre in genres
                }.filterIndexed { n, _ -> n % 2 == i % 2 },
                at = at,
                comment = comment
            )
        }
    }
}
