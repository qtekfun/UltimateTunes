// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.library

import com.qtekfun.ultimatetunes.availability.Availability
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.library.OfflineChanges
import com.qtekfun.ultimatetunes.core.library.PendingStatus
import com.qtekfun.ultimatetunes.core.library.SendResult
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.ui.FakeCatalogRefresh
import com.qtekfun.ultimatetunes.ui.FakeOfflineControls
import com.qtekfun.ultimatetunes.ui.FakePhoneAvailability
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PendingChangesSyncTest {
    private val queued = MutableStateFlow(PendingStatus())
    private val changes = mockk<OfflineChanges> {
        every { status } returns queued
        coEvery { send() } returns SendResult(changed = true)
    }
    private val phone = FakePhoneAvailability(Availability(online = false))
    private val gate = ConnectionGate(
        InMemoryServerConfigSource(
            ServerConfig(
                "https://music.example.net/".toHttpUrl(),
                ApiKeySecret(FakeTunesServer.API_KEY)
            )
        )
    )
    private val refresh = FakeCatalogRefresh()
    private val offline = FakeOfflineControls()
    private var scheduled = 0

    private fun TestScope.started() {
        val scope = CoroutineScope(
            backgroundScope.coroutineContext + UnconfinedTestDispatcher(testScheduler)
        )
        PendingChangesSync(changes, phone, gate, refresh, offline, { scheduled++ }, scope).start()
    }

    @Test
    fun `changes wait for the connection and go when it is back`() = runTest {
        started()
        assertEquals(0, scheduled)

        queued.value = PendingStatus(count = 1, latest = 1)
        assertEquals(1, scheduled)
        coVerify(exactly = 0) { changes.send() }

        phone.availability.value = Availability(online = true)

        coVerify(exactly = 1) { changes.send() }
        assertEquals(1, refresh.requests)

        phone.availability.value = Availability(offlineMode = true)
        queued.value = PendingStatus(count = 2, latest = 2)
        coVerify(exactly = 1) { changes.send() }
    }

    @Test
    fun `a kept playlist is downloaded again once its changes are sent`() = runTest {
        offline.keepCollection(CollectionKind.PLAYLIST, "p1", "Mix")
        val before = offline.syncs
        started()

        queued.value = PendingStatus(playlists = setOf(PlaylistId("p2")))
        queued.value = PendingStatus()
        assertEquals(before, offline.syncs)

        queued.value = PendingStatus(playlists = setOf(PlaylistId("p1")))
        queued.value = PendingStatus()
        assertEquals(before + 1, offline.syncs)
    }
}
