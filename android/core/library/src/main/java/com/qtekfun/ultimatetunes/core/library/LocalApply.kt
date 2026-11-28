// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.library.db.PendingChangeEntity
import com.qtekfun.ultimatetunes.core.library.db.PlaylistEntity
import com.qtekfun.ultimatetunes.core.library.db.PlaylistEntryEntity
import com.qtekfun.ultimatetunes.core.library.db.QueueDao
import com.qtekfun.ultimatetunes.core.library.pending.ChangeKind

/**
 * Makes the catalog show a queued change. Done when the change is made, and again after each
 * sync for what the server does not have yet. Call inside a write transaction.
 */
internal class LocalApply(private val dao: QueueDao) {
    suspend fun apply(change: PendingChangeEntity) {
        val target = change.targetId ?: return
        val data = change.data()
        when (ChangeKind.of(change.kind)) {
            ChangeKind.CREATE -> create(target, data.name.orEmpty())
            ChangeKind.RENAME -> data.name?.let { rename(target, it) }
            ChangeKind.DELETE -> deletePlaylist(target)
            ChangeKind.ADD, ChangeKind.REMOVE, ChangeKind.REORDER -> editSongs(target, change)
            ChangeKind.FAVOURITE_SONG -> favouriteSong(target, data)
            ChangeKind.FAVOURITE_ALBUM -> favouriteAlbum(target, data)
            ChangeKind.SCROBBLE -> dao.played(target, data.at)
            ChangeKind.NOTICE, ChangeKind.ALIAS, null -> Unit
        }
    }

    suspend fun create(id: String, name: String) {
        if (dao.playlist(id) != null) return
        dao.insertPlaylist(
            PlaylistEntity(
                id = id,
                name = name,
                comment = null,
                owner = null,
                isPublic = null,
                readOnly = false,
                songCount = 0,
                duration = 0,
                createdAt = null,
                changedAt = null,
                coverArt = null,
                position = dao.nextPlaylistPosition(),
                searchText = SearchText.of(name)
            )
        )
    }

    suspend fun addSongs(songs: List<Song>) {
        dao.insertSongs(songs.map { it.toEntity(inLibrary = false).copy(starredAt = null) })
    }

    /**
     * Makes [songs] the songs of the playlist [id]; those the catalog does not have are left out.
     * The playlist loses its `changed` mark, so the next sync reads it from the server.
     */
    suspend fun setSongs(id: String, songs: List<String>) {
        val playlist = dao.playlist(id) ?: return
        val durations = songs.distinct().chunked(SQL_VARIABLES)
            .flatMap { dao.durations(it) }
            .associate { it.id to (it.duration ?: 0) }
        val known = songs.filter { it in durations }
        dao.deleteEntries(id)
        dao.insertEntries(known.mapIndexed { i, song -> PlaylistEntryEntity(id, i, song) })
        dao.updatePlaylist(
            playlist.copy(
                songCount = known.size,
                duration = known.sumOf { durations.getValue(it) },
                changedAt = null
            )
        )
    }

    suspend fun deletePlaylist(id: String) {
        dao.deleteEntries(id)
        dao.deletePlaylist(id)
    }

    private suspend fun rename(id: String, name: String) {
        val playlist = dao.playlist(id) ?: return
        dao.updatePlaylist(
            playlist.copy(name = name, changedAt = null, searchText = SearchText.of(name))
        )
    }

    private suspend fun editSongs(id: String, change: PendingChangeEntity) {
        val edit = change.edit() ?: return
        addSongs(change.data().songs)
        setSongs(id, edit.applyTo(dao.entryIds(id)))
    }

    private suspend fun favouriteSong(id: String, data: PendingPayload) {
        addSongs(data.songs)
        if (!data.flag) {
            dao.setSongFavourite(id, null, null)
        } else if (dao.songFavouritePosition(id) == null) {
            dao.setSongFavourite(id, dao.firstSongFavourite() - 1, data.at)
        }
    }

    private suspend fun favouriteAlbum(id: String, data: PendingPayload) {
        if (!data.flag) {
            dao.setAlbumFavourite(id, null, null)
        } else if (dao.albumFavouritePosition(id) == null) {
            dao.setAlbumFavourite(id, dao.firstAlbumFavourite() - 1, data.at)
        }
    }

    private companion object {
        /** Below SQLite's limit of bound values on old Android versions. */
        const val SQL_VARIABLES = 900
    }
}
