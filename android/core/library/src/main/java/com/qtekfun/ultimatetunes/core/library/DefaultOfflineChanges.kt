// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.library.db.PendingChangeEntity
import com.qtekfun.ultimatetunes.core.library.pending.ChangeKind
import com.qtekfun.ultimatetunes.core.library.pending.PlaylistEdit
import java.time.Clock
import java.time.Instant
import java.util.UUID
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.retryWhen

/** [OfflineChanges] over the catalog's database; [CatalogSyncer] does the sending. */
@Suppress("TooManyFunctions")
internal class DefaultOfflineChanges(private val syncer: CatalogSyncer, private val clock: Clock) :
    OfflineChanges {
    private val dao = syncer.queue
    private val local = LocalApply(dao)

    /** A queue that cannot be read shows as empty and is tried again: nothing crashes. */
    private val rows: Flow<List<PendingChangeEntity>> = dao.watch().retryWhen { cause, _ ->
        if (cause is Exception) {
            emit(emptyList())
            delay(RETRY_AFTER_MS)
        }
        cause is Exception
    }

    override val status: Flow<PendingStatus> = rows.map { rows ->
        val waiting = rows.filter {
            ChangeKind.of(it.kind)?.family.let { f -> f != null && f != ChangeKind.Family.NOT_SENT }
        }
        PendingStatus(
            count = waiting.size,
            latest = waiting.maxOfOrNull { it.seq } ?: 0,
            playlists = waiting
                .filter { ChangeKind.of(it.kind)?.family == ChangeKind.Family.PLAYLIST }
                .mapNotNullTo(HashSet()) { row -> row.targetId?.let(::PlaylistId) },
            albumFavourites = waiting
                .filter { it.kind == ChangeKind.FAVOURITE_ALBUM.name }
                .mapNotNull { row -> row.targetId?.let { AlbumId(it) to row.data().flag } }
                .toMap()
        )
    }.distinctUntilChanged()

    override val notices: Flow<List<ChangeNotice>> = rows.map { rows ->
        rows.filter { it.kind == ChangeKind.NOTICE.name }.map {
            val data = it.data()
            ChangeNotice(it.seq, data.name, deletedOnServer = data.flag)
        }
    }.distinctUntilChanged()

    override val replaced: Flow<Map<PlaylistId, PlaylistId>> = rows.map { rows ->
        rows.filter { it.kind == ChangeKind.ALIAS.name }
            .mapNotNull { row ->
                val old = row.targetId ?: return@mapNotNull null
                row.data().removed?.let { PlaylistId(old) to PlaylistId(it) }
            }
            .toMap()
    }.distinctUntilChanged()

    override suspend fun createPlaylist(name: String, songs: List<Song>): PlaylistId? {
        val id = LOCAL_PLAYLIST_PREFIX + UUID.randomUUID()
        val stored = store {
            queue(ChangeKind.CREATE, id, PendingPayload(name = name))
            if (songs.isNotEmpty()) add(id, name, emptyList(), songs)
        }
        return if (stored) PlaylistId(id) else null
    }

    override suspend fun renamePlaylist(playlist: Playlist, name: String): Boolean = store {
        val id = show(playlist)
        queue(ChangeKind.RENAME, id, PendingPayload(name = name))
    }

    override suspend fun deletePlaylist(playlist: Playlist): Boolean = store {
        val id = resolve(playlist.id.value)
        queue(ChangeKind.DELETE, id, PendingPayload(name = playlist.name))
    }

    override suspend fun addToPlaylist(playlist: Playlist, songs: List<Song>): Boolean = store {
        val id = show(playlist)
        add(id, playlist.name, dao.entryIds(id), songs)
    }

    override suspend fun removeFromPlaylist(playlist: Playlist, index: Int): Boolean = store {
        val id = show(playlist)
        val shown = playlist.entry.map { it.id.value }
        val edit = PlaylistEdit.remove(dao.entryIds(id), shown, index)
        queue(
            ChangeKind.REMOVE,
            id,
            PendingPayload(
                name = playlist.name,
                removed = edit.id,
                occurrence = edit.occurrence,
                atMost = edit.atMost
            )
        )
    }

    override suspend fun reorderPlaylist(playlist: Playlist, order: List<SongId>): Boolean = store {
        val id = show(playlist)
        queue(
            ChangeKind.REORDER,
            id,
            PendingPayload(name = playlist.name, ids = order.map { it.value })
        )
    }

    override suspend fun setSongFavourite(song: Song, favourite: Boolean): Boolean = store {
        val data = PendingPayload(songs = listOf(song), flag = favourite, at = clock.millis())
        queue(ChangeKind.FAVOURITE_SONG, song.id.value, data)
    }

    override suspend fun setAlbumFavourite(id: AlbumId, favourite: Boolean): Boolean = store {
        val data = PendingPayload(flag = favourite, at = clock.millis())
        queue(ChangeKind.FAVOURITE_ALBUM, id.value, data)
    }

    override suspend fun scrobble(id: SongId, playedAt: Instant): Boolean = store {
        queue(ChangeKind.SCROBBLE, id.value, PendingPayload(at = playedAt.toEpochMilli()))
    }

    override suspend fun send(): SendResult = syncer.send()

    override suspend fun dismiss(notice: Long) {
        // A notice that cannot be removed is shown again, which is all that happens.
        store { dao.remove(notice) }
    }

    /** One transaction on the catalog of the current connection; false if it could not be made. */
    @Suppress("TooGenericExceptionCaught", "SwallowedException") // Any storage failure.
    private suspend fun store(block: suspend () -> Unit): Boolean = try {
        syncer.writeIfOwned(block)
    } catch (e: CancellationException) {
        throw e
    } catch (e: RuntimeException) {
        false
    }

    private suspend fun queue(kind: ChangeKind, target: String, data: PendingPayload) {
        val row = PendingChangeEntity(
            kind = kind.name,
            targetId = target,
            payload = data.encode(),
            createdAt = clock.millis()
        )
        dao.add(row)
        local.apply(row)
    }

    private suspend fun add(id: String, name: String, current: List<String>, songs: List<Song>) {
        val edit = PlaylistEdit.add(current, songs.map { it.id.value })
        queue(
            ChangeKind.ADD,
            id,
            PendingPayload(name = name, songs = songs, ids = edit.ids, atLeast = edit.atLeast)
        )
    }

    /** The id a playlist goes by now (a screen may still hold the temporary one). */
    private suspend fun resolve(id: String): String = dao.alias(id)?.data()?.removed ?: id

    /**
     * Makes the catalog hold [playlist] as the user sees it, which may be newer than what the last
     * sync read. With changes already waiting the catalog is ahead of any copy, and stays.
     */
    private suspend fun show(playlist: Playlist): String {
        val id = resolve(playlist.id.value)
        if (dao.waitingFor(id) > 0) return id
        local.create(id, playlist.name)
        local.addSongs(playlist.entry)
        local.setSongs(id, playlist.entry.map { it.id.value })
        return id
    }

    private companion object {
        const val RETRY_AFTER_MS = 30_000L
    }
}
