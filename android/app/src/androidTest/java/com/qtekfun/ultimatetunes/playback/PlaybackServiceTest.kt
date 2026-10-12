// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import javax.inject.Inject
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * The app reaches the playback service through a MediaController (PLAN T17): the queue and its
 * metadata go through the session, and a song that cannot load is reported, not a crash. With
 * the UI tests' fake API no server is configured, so nothing plays and nothing is heard.
 */
@HiltAndroidTest
class PlaybackServiceTest {
    @get:Rule
    val hilt = HiltAndroidRule(this)

    @Inject
    lateinit var playback: PlaybackConnection

    private val queue = listOf(
        TrackTile(
            id = SongId("0190a5c8-0000-7000-8000-0000000000f1"),
            title = "Harbour Lights",
            artist = "Northbound Static",
            album = "Low Tide",
            durationSec = 200,
            coverUrl = null,
            isExternal = false,
            albumId = AlbumId("0190a5c8-0000-7000-8000-0000000000a1"),
            trackNumber = 1
        ),
        TrackTile(
            id = SongId("yt:AAAAAAAAAAA"),
            title = "Paper Moons",
            artist = "Northbound Static",
            album = null,
            durationSec = 180,
            coverUrl = null,
            isExternal = true
        )
    )

    @Before
    fun inject() {
        hilt.inject()
    }

    @After
    fun clear() {
        playback.clear()
        runBlocking { withTimeout(TIMEOUT_MS) { playback.state.first { it.queue.isEmpty() } } }
    }

    @Test
    fun theQueueReachesTheSessionAndAnUnloadableSongIsReported() = runBlocking {
        playback.play(queue, startIndex = 1, playWhenReady = false)

        val state = withTimeout(TIMEOUT_MS) {
            playback.state.first { it.queue.size == 2 && it.issue != null }
        }
        assertEquals(queue, state.queue)
        assertEquals(1, state.index)
        assertEquals(PlaybackIssue.UNPLAYABLE, state.issue)
        assertFalse(state.isPlaying)
        // Metadata says 180 s until the player knows better.
        assertEquals(180_000L, state.durationMs)
    }

    private companion object {
        const val TIMEOUT_MS = 20_000L
    }
}
