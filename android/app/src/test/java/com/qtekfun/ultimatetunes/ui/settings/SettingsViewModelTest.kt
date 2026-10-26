// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.settings

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyId
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.offline.LibraryOffline
import com.qtekfun.ultimatetunes.core.player.offline.LibraryReport
import com.qtekfun.ultimatetunes.core.player.offline.LibraryScan
import com.qtekfun.ultimatetunes.core.player.offline.OfflineSelection
import com.qtekfun.ultimatetunes.ui.FakeExports
import com.qtekfun.ultimatetunes.ui.FakeOfflineControls
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.closeForTest
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.dropConnection
import com.qtekfun.ultimatetunes.ui.jsonResponse
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.problem
import java.io.File
import java.time.Instant
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith
import org.junit.jupiter.api.io.TempDir

/** Playback settings kept in memory. */
class FakePlaybackSettings : PlaybackSettingsStore {
    override val settings = MutableStateFlow(PlaybackSettings())

    override suspend fun setCacheSizeMb(value: Int) = settings.update {
        it.copy(cacheSizeMb = value)
    }

    override suspend fun setOfflineOnly(value: Boolean) = settings.update {
        it.copy(offlineOnly = value)
    }

    override suspend fun setDownloadOnWifiOnly(value: Boolean) =
        settings.update { it.copy(downloadOnWifiOnly = value) }

    override suspend fun setLibraryOffline(value: Boolean) = settings.update {
        it.copy(libraryOffline = value)
    }

    override suspend fun setLibraryOfflineLimitMb(value: Int) = settings.update {
        it.copy(libraryOfflineLimitMb = value)
    }
}

@ExtendWith(MainDispatcherExtension::class)
class SettingsViewModelTest {
    private lateinit var server: FakeTunesServer
    private lateinit var configSource: InMemoryServerConfigSource
    private val store = FakePlaybackSettings()
    private val otherKey = ApiKeyId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01f002")
    private val currentKey = ApiKeyId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01f001")

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
        configSource = InMemoryServerConfigSource(server.serverConfig())
    }

    private val created = mutableListOf<SettingsViewModel>()

    @AfterEach
    fun tearDown() {
        // Stop every view model before Main is reset, so no HTTP answer resumes on it later and
        // fails the next test (UncaughtExceptionsBeforeTest).
        created.forEach { it.closeForTest() }
        server.close()
    }

    private val offline = FakeOfflineControls()
    private val exports = FakeExports()

    private fun viewModel() = SettingsViewModel(
        connectedApi(server),
        configSource,
        ConnectionGate(configSource),
        store,
        offline,
        exports
    ).also { created += it }

    private suspend fun SettingsViewModel.loaded(): SettingsUiState =
        state.awaitFirst { it.server !is LoadState.Loading && it.keys !is LoadState.Loading }

    @Test
    fun `the server, the account and this user's keys`() = runTest {
        val state = viewModel().loaded()

        val server = (state.server as LoadState.Ready).value
        assertEquals(this@SettingsViewModelTest.server.baseUrl.toString(), server.address)
        assertEquals("UltimateTunes", server.name)
        assertEquals("0.1.0", server.version)
        assertEquals("alice", server.username)
        assertTrue(server.isAdmin)
        val keys = (state.keys as LoadState.Ready).value
        // The contract's revoked "Old tablet" is left out.
        assertEquals(listOf("Pixel 9"), keys.map { it.name })
        val current = keys.first()
        assertTrue(current.current)
        assertFalse(current.canRevoke)
        assertEquals(Instant.parse("2026-10-12T08:15:30.123Z"), current.lastUsedAt)
        assertEquals(PlaybackSettings(), state.playback)
    }

    @Test
    fun `without server info the account still shows`() = runTest {
        server.dispatcher.override("ut/v1/server") { dropConnection() }

        val server = (viewModel().loaded().server as LoadState.Ready).value

        assertNull(server.name)
        assertNull(server.version)
        assertEquals("alice", server.username)
    }

    @Test
    fun `another device's key can be revoked, and the list reloads`() = runTest {
        var revoked = false
        server.dispatcher.override("ut/v1/keys") {
            val other = if (revoked) {
                ""
            } else {
                """,{"id":"${otherKey.value}","name":"Tablet","prefix":"utk_B","createdAt":"2026-10-02T00:00:00Z"}"""
            }
            jsonResponse(
                """{"keys":[{"id":"${currentKey.value}","name":"Phone","prefix":"utk_A",""" +
                    """"createdAt":"2026-10-01T00:00:00Z","current":true}$other]}"""
            )
        }
        server.dispatcher.override("ut/v1/keys/${otherKey.value}") {
            revoked = true
            mockwebserver3.MockResponse(code = 204)
        }
        val viewModel = viewModel()
        val keys = (viewModel.loaded().keys as LoadState.Ready).value
        assertTrue(keys[1].canRevoke)
        assertNull(keys[1].lastUsedAt)

        viewModel.revoke(currentKey)
        viewModel.revoke(ApiKeyId("unknown"))
        viewModel.revoke(otherKey)

        val after = viewModel.state.awaitFirst { (it.keys as? LoadState.Ready)?.value?.size == 1 }
        assertEquals(listOf("Phone"), (after.keys as LoadState.Ready).value.map { it.name })
        assertTrue(revoked)
    }

    @Test
    fun `nothing is revoked before the keys load`() = runTest {
        val viewModel = viewModel()
        viewModel.revoke(otherKey)
        viewModel.loaded()

        val requests = List(server.requestCount) { server.takeRequest() }
        assertTrue(requests.none { it.method == "DELETE" })
    }

    @Test
    fun `a failed revoke is explained once`() = runTest {
        server.dispatcher.override("ut/v1/keys") {
            jsonResponse(
                """{"keys":[{"id":"${otherKey.value}","name":"Tablet","prefix":"utk_B",""" +
                    """"createdAt":"2026-10-02T00:00:00Z"}]}"""
            )
        }
        server.dispatcher.override("ut/v1/keys/${otherKey.value}") { problem(500, "internal") }
        val viewModel = viewModel()
        viewModel.loaded()

        viewModel.revoke(otherKey)

        assertEquals(LoadError.SERVER, viewModel.state.awaitFirst { it.message != null }.message)
        viewModel.dismissMessage()
        assertNull(viewModel.state.value.message)
    }

    @Test
    fun `failures can be retried`() = runTest {
        server.dispatcher.override("ut/v1/me") { dropConnection() }
        server.dispatcher.override("ut/v1/keys") { dropConnection() }
        val viewModel = viewModel()
        val failed = viewModel.loaded()
        assertEquals(LoadState.Failed(LoadError.NETWORK), failed.server)
        assertEquals(LoadState.Failed(LoadError.NETWORK), failed.keys)

        server.dispatcher.clearOverrides()
        viewModel.load()
        viewModel.load()
        assertTrue(viewModel.loaded().keys is LoadState.Ready)
    }

    @Test
    fun `without a server there is nothing to show`() = runTest {
        configSource.set(null)
        val state = viewModel().loaded()
        assertEquals(LoadState.Failed(LoadError.NOT_CONFIGURED), state.server)
    }

    @Test
    fun `playback choices are kept`() = runTest {
        val viewModel = viewModel()

        viewModel.setCacheSizeMb(5120)
        viewModel.setOfflineOnly(true)
        viewModel.setDownloadOnWifiOnly(false)

        val playback = viewModel.state.awaitFirst { !it.playback.downloadOnWifiOnly }.playback
        assertEquals(
            PlaybackSettings(cacheSizeMb = 5120, offlineOnly = true, downloadOnWifiOnly = false),
            playback
        )
        // The offline sync is scheduled again with the new network rule.
        assertEquals(1, offline.syncs)
    }

    private val mb = 1024L * 1024

    @Test
    fun `the library setting is kept and applied`() = runTest {
        val viewModel = viewModel()

        viewModel.setLibraryOffline(true)
        viewModel.state.awaitFirst { it.playback.libraryOffline }
        assertEquals(1, offline.libraryChanges)

        // The limit applies at once while the setting is on...
        viewModel.setLibraryOfflineLimitMb(20480)
        val playback = viewModel.state.awaitFirst { it.playback.libraryOfflineLimitMb == 20480 }
        assertEquals(
            PlaybackSettings(libraryOffline = true, libraryOfflineLimitMb = 20480),
            playback.playback
        )
        assertEquals(2, offline.libraryChanges)

        viewModel.setLibraryOffline(false)
        viewModel.state.awaitFirst { !it.playback.libraryOffline }
        assertEquals(3, offline.libraryChanges)
    }

    @Test
    fun `a limit picked while the setting is off only changes the preview`() = runTest {
        offline.libraryScan = LibraryScan(
            listOf(
                Song(SongId("a"), "A", size = 600 * mb),
                Song(SongId("b"), "B", size = 600 * mb)
            )
        )
        val viewModel = viewModel()
        val first = viewModel.state.awaitFirst { it.libraryPreview != null }
        // The default 10 GB holds both.
        assertEquals(2, first.libraryPreview?.keptCount)

        viewModel.setLibraryOfflineLimitMb(1024)
        val smaller = viewModel.state.awaitFirst { it.libraryPreview?.keptCount == 1 }

        assertEquals(1, smaller.libraryPreview?.leftOutCount)
        assertEquals(0, offline.libraryChanges)
        assertFalse(smaller.playback.libraryOffline)
    }

    @Test
    fun `what the library setting kept is shown`() = runTest {
        val viewModel = viewModel()
        val kept = LibraryOffline(songs = emptyList(), report = LibraryReport(5, 50, 3, 30, false))

        offline.mutableSelection.value = OfflineSelection(library = kept)

        assertEquals(kept, viewModel.state.awaitFirst { it.libraryKept != null }.libraryKept)
    }

    @Test
    fun `offline mode does not read the library`() = runTest {
        store.setOfflineOnly(true)
        offline.libraryScan = LibraryScan(listOf(Song(SongId("a"), "A", size = mb)))
        val viewModel = viewModel()
        viewModel.loaded()
        assertNull(viewModel.state.value.libraryPreview)
    }

    @Test
    fun `a library the server cannot list shows no size`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()
        assertNull(viewModel.state.value.libraryPreview)
    }

    @Test
    fun `the export folder shows and a picked one is kept`() = runTest {
        val viewModel = viewModel()
        assertNull(viewModel.state.value.exportFolder)

        viewModel.onExportFolderPicked(null)
        assertNull(viewModel.state.value.exportFolder)
        viewModel.onExportFolderPicked("content://tree/primary%3AMusic")

        assertEquals(
            "content://tree/primary%3AMusic",
            viewModel.state.awaitFirst { it.exportFolder != null }.exportFolder
        )
    }

    @Test
    fun `disconnect forgets the server`() {
        viewModel().disconnect()
        assertNull(configSource.config.value)
    }

    @Nested
    inner class Store {
        @TempDir
        lateinit var dir: File

        @Test
        fun `the app prefs keep the export folder and the notification answer`() = runTest {
            val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
            try {
                val prefs = DataStoreAppPrefs(
                    PreferenceDataStoreFactory.create(scope = scope) {
                        File(dir, "app.preferences_pb")
                    }
                )
                assertNull(prefs.exportFolder.first())
                assertFalse(prefs.notificationsAsked.first())

                prefs.setExportFolder("content://tree/x")
                prefs.setNotificationsAsked(true)
                assertEquals("content://tree/x", prefs.exportFolder.first())
                assertTrue(prefs.notificationsAsked.first())

                prefs.setExportFolder(null)
                assertNull(prefs.exportFolder.first())
            } finally {
                scope.cancel()
            }
        }

        @Test
        fun `the DataStore keeps the choices, with RF-12 defaults`() = runTest {
            val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
            try {
                val store = DataStorePlaybackSettings(
                    PreferenceDataStoreFactory.create(scope = scope) {
                        File(dir, "playback.preferences_pb")
                    }
                )
                assertEquals(
                    PlaybackSettings(2048, offlineOnly = false, downloadOnWifiOnly = true),
                    store.settings.first()
                )

                store.setCacheSizeMb(1024)
                store.setOfflineOnly(true)
                store.setDownloadOnWifiOnly(false)

                assertEquals(
                    PlaybackSettings(1024, offlineOnly = true, downloadOnWifiOnly = false),
                    store.settings.first()
                )
            } finally {
                scope.cancel()
            }
        }
    }
}
