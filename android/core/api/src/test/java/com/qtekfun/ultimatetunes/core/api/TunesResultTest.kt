// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api

import com.qtekfun.ultimatetunes.core.api.di.ClockModule
import com.qtekfun.ultimatetunes.core.api.di.TunesApiModule
import java.io.IOException
import java.time.Clock
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class TunesResultTest {
    private val failure: TunesResult<Int> = TunesResult.ApiError(
        TunesError(ErrorKind.NOT_FOUND),
        200
    )

    @Test
    fun `map, getOrNull, onSuccess and onFailure`() {
        val success: TunesResult<Int> = TunesResult.Success(2)
        assertEquals(TunesResult.Success(4), success.map { it * 2 })
        assertEquals(2, success.getOrNull())
        assertSame(failure, failure.map { it * 2 })
        assertNull(failure.getOrNull())

        var seen = 0
        success.onSuccess { seen = it }.onFailure { seen = -1 }
        assertEquals(2, seen)
        failure.onSuccess { seen = it }.onFailure { seen = -1 }
        assertEquals(-1, seen)
    }

    @Test
    fun `a network error does not print its message`() {
        val error = TunesResult.NetworkError(IOException("https://h/rest/ping?apiKey=utk_secret"))
        assertFalse(error.toString().contains("utk_secret"))
        assertTrue(error.toString().contains("IOException"))
    }
}

class TunesApiModuleTest {
    @Test
    fun `the Hilt providers build a working graph`() = runTest {
        val source = TunesApiModule.inMemoryServerConfigSource()
        assertSame(source, TunesApiModule.serverConfigSource(source))
        val client = TunesApiModule.tunesHttpClient(source)
        assertEquals(1, client.networkInterceptors.size)
        val clock: Clock = ClockModule.clock()
        val api = TunesApiModule.tunesApi(client, source, clock)
        assertEquals(TunesResult.NotConfigured, api.ping())
    }
}
