// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.export.ExportStatus
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.core.player.offline.OfflineCollection
import com.qtekfun.ultimatetunes.core.player.offline.OfflineItem
import com.qtekfun.ultimatetunes.core.player.offline.OfflineSelection
import com.qtekfun.ultimatetunes.playback.OfflineControls
import com.qtekfun.ultimatetunes.playback.PlaybackState
import com.qtekfun.ultimatetunes.playback.PlayerController
import com.qtekfun.ultimatetunes.ui.actions.Exports
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.settings.AppPrefsStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update

/*
 * Fakes of the app's own seams (the player, the offline downloads, the export, small prefs): they
 * keep the state a real one would and record what they were asked.
 */

/** A song tile with invented data. */
fun tile(n: Int, external: Boolean = false, durationSec: Int? = 200) = TrackTile(
    id = SongId(if (external) "yt:" + "Song${n}Abcdefghijk".take(11) else "song-$n"),
    title = "Song $n",
    artist = "Invented Artist",
    album = "Invented Album",
    durationSec = durationSec,
    coverUrl = null,
    isExternal = external,
    trackNumber = n
)

/** A player that behaves like the session for the commands the screens send. */
class FakePlayerController(initial: PlaybackState = PlaybackState(connected = true)) :
    PlayerController {
    val mutableState = MutableStateFlow(initial)
    override val state: StateFlow<PlaybackState> = mutableState

    var connects = 0
    val seeks = mutableListOf<Long>()
    var played: Triple<Int, Long, Boolean>? = null

    override fun connect() {
        connects++
    }

    override fun play(
        queue: List<TrackTile>,
        startIndex: Int,
        startPositionMs: Long,
        playWhenReady: Boolean
    ) {
        played = Triple(startIndex, startPositionMs, playWhenReady)
        mutableState.update {
            it.copy(
                queue = queue,
                index = startIndex,
                isPlaying = playWhenReady,
                positionMs = startPositionMs
            )
        }
    }

    override fun playNext(tiles: List<TrackTile>) = mutableState.update {
        val at = if (it.queue.isEmpty()) 0 else it.index + 1
        it.copy(queue = it.queue.take(at) + tiles + it.queue.drop(at))
    }

    override fun enqueue(tiles: List<TrackTile>) = mutableState.update {
        it.copy(queue = it.queue + tiles)
    }

    override fun replaceUpNext(tiles: List<TrackTile>) = mutableState.update {
        it.copy(queue = it.queue.take(it.index + 1) + tiles)
    }

    override fun togglePlayPause() = mutableState.update { it.copy(isPlaying = !it.isPlaying) }

    override fun next() = mutableState.update {
        if (it.hasNext) it.copy(index = it.index + 1, positionMs = 0) else it
    }

    override fun previous() = mutableState.update {
        if (it.hasPrevious) it.copy(index = it.index - 1, positionMs = 0) else it
    }

    override fun seekTo(positionMs: Long) {
        seeks += positionMs
        mutableState.update { it.copy(positionMs = positionMs) }
    }

    override fun playAt(index: Int) = mutableState.update {
        it.copy(index = index, positionMs = 0, isPlaying = true)
    }

    override fun clear() = mutableState.update { it.copy(queue = emptyList(), index = 0) }
}

/** Offline downloads kept in memory; nothing downloads. */
class FakeOfflineControls : OfflineControls {
    val mutableSelection = MutableStateFlow(OfflineSelection())
    val mutableItems = MutableStateFlow<List<OfflineItem>>(emptyList())
    override val selection: Flow<OfflineSelection> = mutableSelection
    override val items: Flow<List<OfflineItem>> = mutableItems
    var syncs = 0

    override suspend fun keepTrack(track: PlayableTrack) = mutableSelection.update {
        it.copy(tracks = it.tracks + track)
    }

    override suspend fun dropTrack(id: SongId) = mutableSelection.update { selection ->
        selection.copy(tracks = selection.tracks.filterNot { it.id == id })
    }

    override suspend fun keepCollection(kind: CollectionKind, id: String, name: String) =
        mutableSelection.update {
            it.copy(collections = it.collections + OfflineCollection(kind, id, name))
        }

    override suspend fun dropCollection(kind: CollectionKind, id: String) =
        mutableSelection.update { selection ->
            selection.copy(
                collections = selection.collections.filterNot { it.kind == kind && it.id == id }
            )
        }

    override suspend fun syncSoon() {
        syncs++
    }
}

/** Exports recorded instead of copied; the folder is granted when set. */
class FakeExports(folder: String? = null) : Exports {
    val mutableStatus = MutableStateFlow<ExportStatus>(ExportStatus.Idle)
    override val status: StateFlow<ExportStatus> = mutableStatus
    private val mutableFolder = MutableStateFlow(folder)
    override val folder: Flow<String?> = mutableFolder
    val started = mutableListOf<Triple<String, List<PlayableTrack>, Map<SongId, SongId>>>()

    override suspend fun setFolder(uri: String) {
        mutableFolder.value = uri
    }

    override fun start(folder: String, tracks: List<PlayableTrack>, aliases: Map<SongId, SongId>) {
        started += Triple(folder, tracks, aliases)
    }

    override fun dismiss() {
        mutableStatus.value = ExportStatus.Idle
    }
}

/** Prefs in memory. */
class FakeAppPrefs : AppPrefsStore {
    private val folder = MutableStateFlow<String?>(null)
    private val asked = MutableStateFlow(false)
    override val exportFolder: Flow<String?> = folder
    override val notificationsAsked: Flow<Boolean> = asked

    override suspend fun setExportFolder(uri: String?) {
        folder.value = uri
    }

    override suspend fun setNotificationsAsked(value: Boolean) {
        asked.value = value
    }
}
