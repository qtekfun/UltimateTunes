// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.availability

import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.library.LibraryRepository
import com.qtekfun.ultimatetunes.core.library.SongRef
import com.qtekfun.ultimatetunes.core.player.offline.OfflineState
import com.qtekfun.ultimatetunes.core.player.session.PhoneLookup
import com.qtekfun.ultimatetunes.core.player.session.PhonePlayback
import com.qtekfun.ultimatetunes.playback.OfflineControls
import com.qtekfun.ultimatetunes.ui.settings.PlaybackSettingsStore
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** What the screens and the player ask about playing from the phone. */
interface PhoneAvailability {
    val availability: StateFlow<Availability>

    /** Looks at the play cache again (it fills while songs play). */
    fun refresh()
}

/**
 * [Availability] from the connection, the offline mode setting, the finished downloads, the songs
 * the play cache holds whole and the catalog.
 */
@Suppress("LongParameterList") // Collaborators are injected one by one.
@Singleton
class AvailabilitySource internal constructor(
    private val connectivity: Connectivity,
    private val settings: PlaybackSettingsStore,
    private val offline: OfflineControls,
    private val cache: CachedSongs,
    repository: LibraryRepository,
    private val scope: CoroutineScope,
    private val io: CoroutineDispatcher
) : PhoneAvailability,
    PhonePlayback {
    @Inject
    constructor(
        connectivity: Connectivity,
        settings: PlaybackSettingsStore,
        offline: OfflineControls,
        cache: CachedSongs,
        repository: LibraryRepository
    ) : this(
        connectivity,
        settings,
        offline,
        cache,
        repository,
        CoroutineScope(SupervisorJob() + Dispatchers.Default),
        Dispatchers.IO
    )

    private val cached = MutableStateFlow<Set<SongId>>(emptySet())

    private val downloaded: Flow<Set<SongId>> = offline.items.map { items ->
        items.filter { it.state == OfflineState.DONE }.mapTo(HashSet()) { it.track.id }
    }

    private val offlineMode: Flow<Boolean> =
        settings.settings.map { it.offlineOnly }.distinctUntilChanged()

    private val onPhone: Flow<Pair<Set<SongId>, Map<SongId, SongId>>> =
        combine(cached, downloaded, offline.selection.map { it.aliases }) { cache, done, aliases ->
            (cache + done) to aliases
        }.distinctUntilChanged()

    override val availability: StateFlow<Availability> = combine(
        connectivity.online,
        offlineMode,
        onPhone,
        repository.songRefs(),
        repository.playlistSongIds()
    ) { online, mode, (songs, aliases), refs, playlists ->
        availabilityOf(Availability(online, mode, songs, aliases), refs, playlists)
    }.stateIn(scope, SharingStarted.Eagerly, Availability(online = connectivity.online.value))

    init {
        scope.launch {
            combine(connectivity.online, offlineMode, ::Pair).distinctUntilChanged()
                .collect { refresh() }
        }
    }

    override fun refresh() {
        scope.launch { readCache() }
    }

    override fun onlyPhone(): Boolean = !connectivity.online.value || availability.value.offlineMode

    override suspend fun songs(): PhoneLookup {
        val songs = readCache() + downloaded.first()
        val aliases = offline.selection.first().aliases
        return PhoneLookup { phoneIdIn(songs, aliases, it) }
    }

    private suspend fun readCache(): Set<SongId> =
        withContext(io) { cache.complete() }.also { cached.value = it }

    private fun availabilityOf(
        base: Availability,
        refs: List<SongRef>,
        entries: Map<PlaylistId, List<SongId>>
    ): Availability {
        val albums = HashSet<AlbumId>()
        val artists = HashSet<ArtistId>()
        refs.filter { base.phoneId(it.id) != null }.forEach { ref ->
            ref.albumId?.let(albums::add)
            ref.artistId?.let(artists::add)
            ref.albumArtistId?.let(artists::add)
        }
        val playlists = entries.filterValues { ids -> ids.any { base.phoneId(it) != null } }.keys
        return base.copy(albums = albums, artists = artists, playlists = playlists.toSet())
    }
}
