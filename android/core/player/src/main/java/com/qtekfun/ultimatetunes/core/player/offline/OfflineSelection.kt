// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.offline

import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import kotlinx.serialization.Serializable

/** What the user keeps on the phone (RF-12): single songs, albums and playlists. */
@Serializable
data class OfflineSelection(
    val tracks: List<PlayableTrack> = emptyList(),
    val collections: List<OfflineCollection> = emptyList(),
    /**
     * `yt:` ids already archived by the server, with their library id: offline downloads are
     * always library files, so a `yt:` song is downloaded under the id it got.
     */
    val aliases: Map<SongId, SongId> = emptyMap(),
    /** The whole library kept because of the setting; null when it is off. */
    val library: LibraryOffline? = null
) {
    val isEmpty: Boolean get() = tracks.isEmpty() && collections.isEmpty() && library == null

    /**
     * The library songs the user keeps on their own, as downloads know them: the single songs and
     * the members of the kept albums and playlists (a `yt:` song by the library id it got). The
     * library setting never evicts these and does not count them against its limit.
     */
    fun explicitIds(): Set<SongId> =
        (tracks + collections.flatMap { it.members.orEmpty() }).mapTo(HashSet()) {
            if (it.isExternal) aliases[it.id] ?: it.id else it.id
        }

    /** True when the song [id] is kept on its own. */
    fun keepsTrack(id: SongId): Boolean = tracks.any { it.id == id }

    /** True when the album or playlist [id] of [kind] is kept. */
    fun keepsCollection(kind: CollectionKind, id: String): Boolean =
        collections.any { it.kind == kind && it.id == id }
}

/** An album or playlist kept offline; it stays in sync with the server. */
@Serializable
data class OfflineCollection(
    val kind: CollectionKind,
    val id: String,
    val name: String,
    /** Its songs at the last successful sync; null until the first one. */
    val members: List<PlayableTrack>? = null
)

@Serializable
enum class CollectionKind { ALBUM, PLAYLIST }
