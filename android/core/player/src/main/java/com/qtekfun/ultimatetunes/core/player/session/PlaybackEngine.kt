// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.session

import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.Timeline
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.cache.CacheJanitor
import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy
import com.qtekfun.ultimatetunes.core.player.cache.PollStep
import com.qtekfun.ultimatetunes.core.player.cache.StatusPoller
import com.qtekfun.ultimatetunes.core.player.gain.ReplayGainPolicy
import com.qtekfun.ultimatetunes.core.player.gain.ReplayGainSource
import com.qtekfun.ultimatetunes.core.player.media.MediaItems
import com.qtekfun.ultimatetunes.core.player.prefetch.PrefetchPlanner
import com.qtekfun.ultimatetunes.core.player.prefetch.Prefetcher
import com.qtekfun.ultimatetunes.core.player.prefetch.QueueSnapshot
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Everything the player does around the songs it plays, on the player's thread ([scope] must run
 * there): prefetch of the next songs, first-play status polling of `yt:` songs (switching the
 * queue to the library id once archived), cache upkeep and ReplayGain. It also skips a song that
 * fails to load, a few times in a row at most, so one broken download does not stop the queue.
 * When the server cannot be reached it goes straight on to the next song the phone holds,
 * however far down the queue.
 */
// Collaborators are injected one by one (tests); one callback per player event, one step each.
@Suppress("LongParameterList", "TooManyFunctions")
class PlaybackEngine(
    private val player: Player,
    private val api: TunesApi,
    private val prefetcher: Prefetcher,
    private val poller: StatusPoller,
    private val janitor: CacheJanitor,
    private val gains: ReplayGainSource,
    private val phone: PhonePlayback,
    private val scope: CoroutineScope,
    private val io: CoroutineDispatcher
) : Player.Listener {
    /** Read on every queue move; the app's "offline only" setting. */
    @Volatile
    var offlineOnly: Boolean = false

    private var current: SongId? = null
    private var polling: Job? = null
    private val upcomingPolls = mutableMapOf<SongId, Job>()
    private var gainJob: Job? = null
    private var failuresInARow = 0
    private var skipping: Job? = null

    /** The songs that failed since something last played: never gone back to in the same run. */
    private val failedInARow = mutableSetOf<SongId>()

    /** The songs that failed to load in this session, newest last. */
    val failed: List<SongId> get() = failedSongs.toList()
    private val failedSongs = ArrayDeque<SongId>()

    fun start() {
        player.addListener(this)
        onQueueMoved()
    }

    fun release() {
        player.removeListener(this)
        prefetcher.cancel()
        polling?.cancel()
        upcomingPolls.values.forEach(Job::cancel)
        upcomingPolls.clear()
        gainJob?.cancel()
        skipping?.cancel()
        // Entries left incomplete now are swept on the first queue move of the next session.
    }

    override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) = onQueueMoved()

    override fun onIsPlayingChanged(isPlaying: Boolean) {
        if (isPlaying) {
            failuresInARow = 0
            failedInARow.clear()
        }
    }

    override fun onTimelineChanged(timeline: Timeline, reason: Int) = onQueueMoved()

    override fun onPlayerError(error: PlaybackException) {
        current?.let {
            remember(it)
            failedInARow += it
        }
        failuresInARow++
        if (phone.onlyPhone() || error.errorCode in UNREACHABLE) {
            skipToPhoneSong()
        } else {
            skipOne()
        }
    }

    private fun skipOne() {
        if (failuresInARow <= MAX_SKIPS_IN_A_ROW && player.hasNextMediaItem()) {
            player.seekToNextMediaItem()
            player.prepare()
        }
    }

    /**
     * Plays the first song from the current one on that the phone holds: the current one itself
     * under the library id it was kept as, or a later one. With a connection and none, the next
     * song is tried as after any other error.
     */
    private fun skipToPhoneSong() {
        skipping?.cancel()
        skipping = scope.launch {
            val songs = phone.songs()
            if (!playFromPhone(songs) && !phone.onlyPhone()) skipOne()
        }
    }

    private fun playFromPhone(songs: PhoneLookup): Boolean {
        val from = player.currentMediaItemIndex
        val found = playOrderFrom(from).firstNotNullOfOrNull { index ->
            val id = MediaItems.songOf(player.getMediaItemAt(index))
            // The song that just failed is only tried again under another id.
            songs.phoneId(id)
                ?.takeUnless { it in failedInARow || (index == from && it == id) }
                ?.let { index to it }
        }
        found?.let { (index, local) -> playAt(index, local) }
        return found != null
    }

    private fun playAt(index: Int, local: SongId) {
        val item = player.getMediaItemAt(index)
        if (local != MediaItems.songOf(item)) {
            player.replaceMediaItem(index, MediaItems.withId(item, local, api))
        }
        player.seekTo(index, 0)
        player.prepare()
    }

    /** The queue positions from [from] on, in play order, each once. */
    private fun playOrderFrom(from: Int): Sequence<Int> {
        val timeline = player.currentTimeline
        if (timeline.isEmpty) return emptySequence()
        val repeat =
            player.repeatMode.takeIf { it != Player.REPEAT_MODE_ONE } ?: Player.REPEAT_MODE_OFF
        val seen = mutableSetOf<Int>()
        return generateSequence(from) {
            timeline.getNextWindowIndex(it, repeat, player.shuffleModeEnabled)
        }.takeWhile { it != C.INDEX_UNSET && seen.add(it) }
    }

    private fun remember(id: SongId) {
        failedSongs.addLast(id)
        if (failedSongs.size > MAX_FAILED_REMEMBERED) failedSongs.removeFirst()
    }

    /** The queue or the position in it changed. */
    private fun onQueueMoved() {
        val now = player.currentMediaItem?.let(MediaItems::songOf)
        val upcoming = upcoming()

        prefetcher.onQueueChanged(QueueSnapshot(now, upcoming, offlineOnly))
        sweep(inUse = (upcoming + listOfNotNull(now)).mapTo(HashSet(), CachePolicy::cacheKey))

        if (now != current) {
            current = now
            startPolling(now)
            applyGain()
        }
        followUpcoming(upcoming.filter { it != now && it.isExternal && !offlineOnly }.toSet())
    }

    private fun sweep(inUse: Set<String>) {
        val archived = poller.archived.keys
        scope.launch { withContext(io) { janitor.sweep(inUse, archived) } }
    }

    private fun startPolling(id: SongId?) {
        polling?.cancel()
        if (id == null || !id.isExternal || offlineOnly) return
        polling = scope.launch {
            val archived = poller.archivedNow(id)
            if (archived != null) {
                playFromLibrary(id, archived)
                return@launch
            }
            val step = poller.pollUntilSettled(id)
            if (step is PollStep.Archived) switchToLibrary(id, step.libraryId)
        }
    }

    /** The next [PrefetchPlanner.UPCOMING_SONGS] songs, in play order (shuffle, repeat applied). */
    private fun upcoming(): List<SongId> {
        val timeline = player.currentTimeline
        // As Media3 navigates: repeating one song still moves on to the next one in the queue.
        val repeat =
            player.repeatMode.takeIf { it != Player.REPEAT_MODE_ONE } ?: Player.REPEAT_MODE_OFF
        val songs = mutableListOf<SongId>()
        var index = if (timeline.isEmpty) C.INDEX_UNSET else player.currentMediaItemIndex
        while (index != C.INDEX_UNSET && songs.size < PrefetchPlanner.UPCOMING_SONGS) {
            index = timeline.getNextWindowIndex(index, repeat, player.shuffleModeEnabled)
            if (index != C.INDEX_UNSET) songs += MediaItems.songOf(player.getMediaItemAt(index))
        }
        return songs
    }

    /**
     * Follows the upcoming `yt:` songs [ids] too: the server downloads them ahead (prefetch) and
     * the next one's raw start is preloaded, so once one is archived the queue must play its
     * library id, never the `yt:` id (whose cached start would be continued with the bytes of a
     * different file).
     */
    private fun followUpcoming(ids: Set<SongId>) {
        val gone = upcomingPolls.keys - ids
        gone.forEach { upcomingPolls.remove(it)?.cancel() }
        for (id in ids - upcomingPolls.keys) {
            upcomingPolls[id] = scope.launch {
                val step = poller.pollUntilSettled(id)
                if (step is PollStep.Archived) switchToLibrary(id, step.libraryId)
            }
        }
    }

    /** The song playing now, [external], switches to [libraryId] where it is (and its copies). */
    private fun playFromLibrary(external: SongId, libraryId: SongId) {
        val index = player.currentMediaItemIndex
        val item = player.currentMediaItem ?: return
        if (MediaItems.songOf(item) != external) return
        val position = player.currentPosition
        switchToLibrary(external, libraryId)
        player.replaceMediaItem(index, MediaItems.withId(item, libraryId, api))
        player.seekTo(index, position)
    }

    /** Queue entries of [external] other than the one playing now become [libraryId]. */
    private fun switchToLibrary(external: SongId, libraryId: SongId) {
        for (index in 0 until player.mediaItemCount) {
            val item = player.getMediaItemAt(index)
            if (index != player.currentMediaItemIndex && MediaItems.songOf(item) == external) {
                player.replaceMediaItem(index, MediaItems.withId(item, libraryId, api))
            }
        }
    }

    private fun applyGain() {
        gainJob?.cancel()
        val index = player.currentMediaItemIndex
        val item = player.currentMediaItem ?: return
        val albumMode = ReplayGainPolicy.isAlbumMode(
            previous = albumAt(player.previousMediaItemIndex),
            current = MediaItems.albumOf(item),
            next = albumAt(player.nextMediaItemIndex)
        )
        val id = MediaItems.songOf(item)
        // Set at once, so the song never starts at the previous song's volume (or at unity).
        val (known, remembered) = gains.remembered(id)
        player.volume = ReplayGainPolicy.volume(remembered, albumMode, gains.unknownDb())
        if (known || offlineOnly || id.isExternal) return
        gainJob = scope.launch {
            val gain = gains.gainOf(id)
            if (player.currentMediaItemIndex == index) {
                player.volume = ReplayGainPolicy.volume(gain, albumMode, gains.unknownDb())
            }
        }
    }

    private fun albumAt(index: Int) =
        if (index == C.INDEX_UNSET) null else MediaItems.albumOf(player.getMediaItemAt(index))

    private companion object {
        /** Songs skipped after load errors before the player stops and shows the error. */
        const val MAX_SKIPS_IN_A_ROW = 3
        const val MAX_FAILED_REMEMBERED = 50

        /** Errors that say the server could not be reached, not that the song is broken. */
        val UNREACHABLE = setOf(
            PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED,
            PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT
        )
    }
}
