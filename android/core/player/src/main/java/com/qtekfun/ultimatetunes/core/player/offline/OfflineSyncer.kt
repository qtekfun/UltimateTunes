// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.offline

import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.map
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.RequestReason
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.TrackState
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.PlayerSettings
import com.qtekfun.ultimatetunes.core.player.PlayerSettingsSource
import kotlinx.coroutines.flow.first

/** The offline downloads as the syncer sees them (Media3's download manager in the app). */
interface DownloadQueue {
    /** Every download, in any state (queued, downloading, done or failed). */
    suspend fun knownIds(): Set<SongId>

    /** The downloads that failed (retried when still wanted, removable like any other). */
    suspend fun failedIds(): Set<SongId>

    /** Downloads [track] (a library song). */
    suspend fun add(track: PlayableTrack)

    /** Removes the download of [id] and frees its space. */
    suspend fun remove(id: SongId)
}

/**
 * One offline sync (RF-12): reads every kept album and playlist from the server, asks the server
 * to keep the `yt:` songs (so they become library songs), then adds and removes downloads per
 * [OfflineSyncPlanner]. An album or playlist that cannot be read keeps its last known songs.
 * With "Keep my whole library offline" on, it also reads the library and keeps the songs that fit
 * the limit ([LibrarySelector]); with it off, it drops them, which frees what only that setting
 * had downloaded.
 */
class OfflineSyncer(
    private val api: TunesApi,
    private val store: OfflineSelectionStore,
    private val queue: DownloadQueue,
    private val settings: PlayerSettingsSource
) {
    suspend fun sync(): SyncPlan {
        val before = store.selection.first()
        val members = before.collections.associate { (it.kind to it.id) to fetchMembers(it) }
        val wanted = before.tracks + before.collections.flatMap {
            members[it.kind to it.id] ?: it.members.orEmpty()
        }
        val learned = mutableMapOf<SongId, SongId>()
        for (id in wanted.map {
            it.id
        }.filter { it.isExternal && it !in before.aliases }.distinct()) {
            archivedId(id)?.let { learned[id] = it }
        }

        val scan = if (settings.settings.first().libraryOffline) readLibrary() else null
        // Read again: the setting may have been turned off while the sync was reading.
        val prefs = settings.settings.first()

        var after = before
        store.update { current ->
            val updated = current.copy(
                collections = current.collections.map { collection ->
                    members[collection.kind to collection.id]
                        ?.let { collection.copy(members = it) } ?: collection
                },
                aliases = current.aliases + learned
            )
            updated.copy(library = libraryAfterSync(updated, prefs, scan)).also { after = it }
        }

        val plan = OfflineSyncPlanner.plan(after, queue.knownIds(), queue.failedIds())
        plan.remove.forEach { queue.remove(it) }
        plan.add.forEach { queue.add(it) }
        return plan
    }

    /**
     * What the stored library becomes after a sync that read [scan]: nothing when the setting was
     * turned off, the songs that fit the limit when the library was read, and the previous
     * result (or "not read yet") when it could not be.
     */
    private fun libraryAfterSync(
        selection: OfflineSelection,
        prefs: PlayerSettings,
        scan: LibraryScan?
    ): LibraryOffline? = when {
        !prefs.libraryOffline -> null
        scan == null -> selection.library ?: LibraryOffline()
        else -> fitted(scan, prefs.libraryOfflineLimitBytes, selection.explicitIds())
    }

    private fun fitted(scan: LibraryScan, limitBytes: Long, explicit: Set<SongId>): LibraryOffline {
        val picked = LibrarySelector.select(scan.candidates, limitBytes, explicit)
        val chosen = picked.chosen.mapTo(HashSet()) { it.id }
        return LibraryOffline(
            songs = scan.songs.filter { it.id in chosen }.sortedBy { it.id.value }.map {
                PlayableTrack.of(it, api)
            },
            report = picked.report
        )
    }

    /**
     * Reads the whole library, a page at a time (an empty `search3`); null when any page fails, so
     * a flaky network never shrinks the kept library.
     */
    suspend fun readLibrary(): LibraryScan? {
        val songs = LinkedHashMap<SongId, Song>()
        var offset = 0
        while (offset < MAX_LIBRARY_SONGS) {
            val page = (api.librarySongs(offset, PAGE_SIZE) as? TunesResult.Success)?.value
                ?: return null
            page.filterNot { it.isExternal }.forEach { songs.putIfAbsent(it.id, it) }
            if (page.size < PAGE_SIZE) break
            offset += PAGE_SIZE
        }
        return LibraryScan(songs.values.toList())
    }

    /**
     * Removes the downloads the stored selection no longer wants, without asking the server;
     * [dropped] are the songs the user just let go (freed even while some kept album or playlist
     * was never read).
     */
    suspend fun prune(dropped: Set<SongId> = emptySet()): Set<SongId> {
        val plan = OfflineSyncPlanner.plan(
            store.selection.first(),
            queue.knownIds(),
            dropped = dropped
        )
        plan.remove.forEach { queue.remove(it) }
        return plan.remove
    }

    private suspend fun fetchMembers(collection: OfflineCollection): List<PlayableTrack>? {
        val songs = when (collection.kind) {
            CollectionKind.ALBUM -> api.album(AlbumId(collection.id)).map { it.song }
            CollectionKind.PLAYLIST -> api.playlist(PlaylistId(collection.id)).map { it.entry }
        }
        return (songs as? TunesResult.Success)?.value?.map { PlayableTrack.of(it, api) }
    }

    /** Asks the server to keep [id]; its library id once it is archived, else null. */
    private suspend fun archivedId(id: SongId): SongId? {
        val status = (api.requestTrack(id, RequestReason.KEEP) as? TunesResult.Success)?.value
        return status?.trackId?.takeIf { status.state == TrackState.READY && it != id }
    }

    private companion object {
        /** The most `search3` returns for one page. */
        const val PAGE_SIZE = 500

        /** A guard against a server that never ends a listing. */
        const val MAX_LIBRARY_SONGS = 200_000
    }
}

/** The library as read from the server: what the sync and the Settings preview work on. */
class LibraryScan(val songs: List<Song>) {
    val candidates: List<LibraryCandidate> by lazy { songs.map(LibraryCandidate::of) }

    /** How the library compares with [limitBytes], leaving out what is [alreadyKept]. */
    fun report(limitBytes: Long, alreadyKept: Set<SongId>): LibraryReport =
        LibrarySelector.select(candidates, limitBytes, alreadyKept).report
}
