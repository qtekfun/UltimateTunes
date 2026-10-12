// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.gain

import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ReplayGain
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import java.io.IOException
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ReplayGainPolicyTest {
    private val album = AlbumId("al-1")
    private val other = AlbumId("al-2")

    @Test
    fun `album mode needs a neighbour from the same album`() {
        assertTrue(ReplayGainPolicy.isAlbumMode(album, album, null))
        assertTrue(ReplayGainPolicy.isAlbumMode(null, album, album))
        assertFalse(ReplayGainPolicy.isAlbumMode(other, album, other))
        assertFalse(ReplayGainPolicy.isAlbumMode(null, null, null))
    }

    @Test
    fun `no gain plays at unity`() {
        assertEquals(1f, ReplayGainPolicy.volume(null, albumMode = false))
        assertEquals(1f, ReplayGainPolicy.volume(ReplayGain(), albumMode = true))
    }

    @Test
    fun `a negative gain attenuates`() {
        val gain = ReplayGain(trackGain = -6.0, albumGain = -12.0)
        assertEquals(0.501f, ReplayGainPolicy.volume(gain, albumMode = false), 0.001f)
        assertEquals(0.251f, ReplayGainPolicy.volume(gain, albumMode = true), 0.001f)
    }

    @Test
    fun `each mode falls back to the other gain and peak`() {
        assertEquals(
            0.501f,
            ReplayGainPolicy.volume(ReplayGain(albumGain = -6.0), albumMode = false),
            0.001f
        )
        assertEquals(
            0.501f,
            ReplayGainPolicy.volume(ReplayGain(trackGain = -6.0), albumMode = true),
            0.001f
        )
        assertEquals(
            0.4f,
            ReplayGainPolicy.volume(ReplayGain(trackGain = -3.0, albumPeak = 2.5), false),
            0.001f
        )
        assertEquals(
            0.4f,
            ReplayGainPolicy.volume(ReplayGain(albumGain = -3.0, trackPeak = 2.5), true),
            0.001f
        )
    }

    @Test
    fun `a positive gain is capped at unity and the peak prevents clipping`() {
        assertEquals(1f, ReplayGainPolicy.volume(ReplayGain(trackGain = 4.0), false))
        assertEquals(
            0.8f,
            ReplayGainPolicy.volume(ReplayGain(trackGain = 0.0, trackPeak = 1.25), false),
            0.001f
        )
        // A zero peak means unknown: ignored.
        assertEquals(
            1f,
            ReplayGainPolicy.volume(ReplayGain(trackGain = 0.0, trackPeak = 0.0), false)
        )
    }
}

class ReplayGainSourceTest {
    private val id = SongId("0190a5c8-0000-7000-8000-000000000001")
    private val api = mockk<TunesApi>()

    @Test
    fun `gains come from getSong and are remembered`() = runTest {
        val gain = ReplayGain(trackGain = -5.0)
        coEvery { api.song(id) } returns TunesResult.Success(Song(id, "T", replayGain = gain))
        val source = ReplayGainSource(api)

        assertEquals(gain, source.gainOf(id))
        assertEquals(gain, source.gainOf(id))
        coVerify(exactly = 1) { api.song(id) }
    }

    @Test
    fun `a song without gain is remembered as such`() = runTest {
        coEvery { api.song(id) } returns TunesResult.Success(Song(id, "T"))
        val source = ReplayGainSource(api)
        assertNull(source.gainOf(id))
        assertNull(source.gainOf(id))
        coVerify(exactly = 1) { api.song(id) }
    }

    @Test
    fun `failures are retried and external songs are never asked`() = runTest {
        coEvery { api.song(id) } returns TunesResult.NetworkError(IOException("x"))
        val source = ReplayGainSource(api)
        assertNull(source.gainOf(id))
        assertNull(source.gainOf(id))
        assertNull(source.gainOf(SongId("yt:AAAAAAAAAAA")))
        coVerify(exactly = 2) { api.song(any()) }
    }

    @Test
    fun `only the most recent songs are remembered`() = runTest {
        val second = SongId("0190a5c8-0000-7000-8000-000000000002")
        coEvery { api.song(id) } returns TunesResult.Success(Song(id, "T"))
        coEvery { api.song(second) } returns TunesResult.Success(Song(second, "T"))
        val source = ReplayGainSource(api, capacity = 1)
        source.gainOf(id)
        source.gainOf(second)
        source.gainOf(id)
        coVerify(exactly = 2) { api.song(id) }
    }
}
