// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.ErrorKind
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.library.db.CatalogSnapshot
import com.qtekfun.ultimatetunes.core.library.db.SyncDao

/** Ends a sync early; caught by [CatalogSyncer] and turned into its result. */
internal class SyncStopped(val result: CatalogSyncResult) : Exception()

/** The value of this answer; a failure stops the sync, so nothing partial is ever stored. */
internal fun <T> TunesResult<T>.orStop(): T = when (this) {
    is TunesResult.Success -> value

    is TunesResult.Failure ->
        throw SyncStopped(CatalogSyncResult.Failed(CatalogSyncError.Server(this)))
}

/** Reads from the server everything the catalog stores. Any call that fails stops the sync. */
internal class CatalogReader(
    private val api: TunesApi,
    private val stored: SyncDao,
    private val pageSize: Int
) {
    suspend fun read(): CatalogSnapshot {
        val library = readLibrary()
        val playlists = readPlaylists(library.keys)
        val starred = api.starred().orStop()
        return SnapshotBuilder.build(library.values, playlists, starred)
    }

    /** Every library song by id, a page of an empty `search3` at a time. */
    private suspend fun readLibrary(): Map<String, Song> {
        val songs = LinkedHashMap<String, Song>()
        var offset = 0
        while (offset < MAX_LIBRARY_SONGS) {
            val page = api.librarySongs(offset, pageSize).orStop()
            page.filterNot { it.isExternal }.forEach { songs.putIfAbsent(it.id.value, it) }
            if (page.size < pageSize) break
            offset += pageSize
        }
        return songs
    }

    /**
     * Every playlist with its songs. One whose `changed` and size are as stored is not asked for
     * again, unless it holds songs outside the library: those turn into library songs (a new id)
     * without the playlist changing.
     */
    private suspend fun readPlaylists(library: Set<String>): List<PlaylistSongs> {
        val listed = api.playlists().orStop()
        val before = stored.storedPlaylists().associateBy { it.id }
        val entries = stored.storedEntries().groupBy({ it.playlistId }, { it.songId })
        return listed.mapNotNull { playlist ->
            val changedAt = before[playlist.id.value]?.changedAt
            val ids = entries[playlist.id.value].orEmpty()
            val unchanged = changedAt != null &&
                changedAt == playlist.changed?.toEpochMilli() &&
                ids.size == playlist.songCount &&
                ids.all { it in library }
            if (unchanged) PlaylistSongs.Kept(playlist, ids) else readPlaylist(playlist)
        }
    }

    /** [listed] with its songs; null when it was deleted since it was listed. */
    private suspend fun readPlaylist(listed: Playlist): PlaylistSongs? {
        val result = api.playlist(listed.id)
        if ((result as? TunesResult.ApiError)?.error?.kind == ErrorKind.NOT_FOUND) return null
        val playlist = result.orStop()
        return PlaylistSongs.Read(playlist, playlist.entry)
    }

    private companion object {
        /** A guard against a server that never ends a listing. */
        const val MAX_LIBRARY_SONGS = 200_000
    }
}
