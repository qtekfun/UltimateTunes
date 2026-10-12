// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import app.cash.turbine.test
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesApiFactory
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.jupiter.api.extension.AfterEachCallback
import org.junit.jupiter.api.extension.BeforeEachCallback
import org.junit.jupiter.api.extension.ExtensionContext

/** Runs view-model coroutines (`viewModelScope`, on Main) on a test dispatcher. */
@OptIn(ExperimentalCoroutinesApi::class)
class MainDispatcherExtension :
    BeforeEachCallback,
    AfterEachCallback {
    override fun beforeEach(context: ExtensionContext) {
        Dispatchers.setMain(UnconfinedTestDispatcher())
    }

    override fun afterEach(context: ExtensionContext) {
        Dispatchers.resetMain()
    }
}

/** A fixed clock for the API client. */
val testClock: Clock = Clock.fixed(Instant.parse("2026-10-12T08:00:00Z"), ZoneOffset.UTC)

/** A real [TunesApi] reading its configuration from [source] (empty unless given). */
fun apiWith(source: InMemoryServerConfigSource): TunesApi =
    TunesApiFactory.create(TunesApiFactory.httpClient(source), source, testClock)

/** A real [TunesApi] connected to [server] with the valid key. */
fun connectedApi(server: FakeTunesServer): TunesApi = server.createApi(testClock)

/** The first value of this flow matching [predicate], skipping the others (Turbine). */
suspend fun <T : Any> Flow<T>.awaitFirst(predicate: (T) -> Boolean): T {
    var found: T? = null
    test {
        while (found == null) {
            val item = awaitItem()
            if (predicate(item)) found = item
        }
        cancelAndIgnoreRemainingEvents()
    }
    return checkNotNull(found)
}
