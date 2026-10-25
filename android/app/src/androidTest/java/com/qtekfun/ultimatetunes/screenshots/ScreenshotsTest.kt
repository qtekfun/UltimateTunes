// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

@file:OptIn(UnstableApi::class)

package com.qtekfun.ultimatetunes.screenshots

import android.app.LocaleManager
import android.app.UiModeManager
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.graphics.Bitmap
import android.os.Build
import android.os.LocaleList
import android.os.SystemClock
import androidx.annotation.OptIn
import androidx.annotation.StringRes
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.DatabaseProvider
import androidx.media3.datasource.cache.NoOpCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesApiFactory
import com.qtekfun.ultimatetunes.core.api.di.TunesHttpClient
import com.qtekfun.ultimatetunes.core.player.PlayerSettingsSource
import com.qtekfun.ultimatetunes.core.player.cache.AdjustableLruEvictor
import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy
import com.qtekfun.ultimatetunes.core.player.di.PlayerModule
import com.qtekfun.ultimatetunes.core.player.media.MediaCaches
import com.qtekfun.ultimatetunes.core.player.media.MediaDataSources
import com.qtekfun.ultimatetunes.core.player.offline.DataStoreOfflineSelection
import com.qtekfun.ultimatetunes.core.player.offline.OfflineDownloads
import com.qtekfun.ultimatetunes.core.player.offline.OfflineSelectionStore
import com.qtekfun.ultimatetunes.core.player.offline.OfflineSyncer
import com.qtekfun.ultimatetunes.playback.PlaybackConnection
import com.qtekfun.ultimatetunes.ui.FakeTunesApiBindings
import com.qtekfun.ultimatetunes.ui.MainActivity
import com.qtekfun.ultimatetunes.ui.album.ALBUM_LIST_TAG
import com.qtekfun.ultimatetunes.ui.connect.DemoServer
import com.qtekfun.ultimatetunes.ui.designsystem.TITLE_TAG
import com.qtekfun.ultimatetunes.ui.listennow.LISTEN_NOW_LIST_TAG
import com.qtekfun.ultimatetunes.ui.lyrics.LYRICS_ACTIVE_LINE_TAG
import com.qtekfun.ultimatetunes.ui.lyrics.LYRICS_TAG
import com.qtekfun.ultimatetunes.ui.navigation.Tab
import com.qtekfun.ultimatetunes.ui.player.FULL_PLAYER_TAG
import com.qtekfun.ultimatetunes.ui.player.LYRICS_BUTTON_TAG
import com.qtekfun.ultimatetunes.ui.player.MINI_PLAYER_TAG
import com.qtekfun.ultimatetunes.ui.search.SEARCH_FIELD_TAG
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import dagger.hilt.android.testing.UninstallModules
import dagger.hilt.components.SingletonComponent
import java.io.File
import java.time.Clock
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * The store and README screenshots (PLAN T23): the app against the debug demo server, so every
 * artist, song and cover is invented (CLAUDE.md). Off by default: `fastlane/screenshots.sh` runs
 * it (`am instrument -e screenshots true`) and copies the pictures from the app's
 * `files/screenshots/` into `fastlane/` and `docs/images/`.
 *
 * Only this app is touched: its language and theme are set per app (Android 13+) and restored
 * after each test; the play cache, downloads and offline selection live in a scratch folder of the
 * app's cache, deleted at the end, so the installed app's own cache, downloads and choices are left
 * as they were. Only Coil's image cache keeps the demo covers (keyed by a loopback URL that no real
 * server uses, evicted like any other image). The demo plays a soft chord for a few seconds per
 * tour, then stops.
 */
@HiltAndroidTest
@UninstallModules(FakeTunesApiBindings::class, PlayerModule::class)
class ScreenshotsTest {
    @get:Rule(order = 0)
    val hilt = HiltAndroidRule(this)

    @get:Rule(order = 1)
    val compose = createEmptyComposeRule()

    @Inject
    lateinit var configSource: InMemoryServerConfigSource

    @Inject
    lateinit var demo: DemoServer

    @Inject
    lateinit var playback: PlaybackConnection

    private val context: Context = InstrumentationRegistry.getInstrumentation().targetContext
    private var scenario: ActivityScenario<MainActivity>? = null
    private var index = 0

    /** The demo's real HTTP stack instead of the UI tests' fake API. */
    @Module
    @InstallIn(SingletonComponent::class)
    object DemoApiModule {
        @Provides
        @Singleton
        @TunesHttpClient
        fun tunesHttpClient(configSource: ServerConfigSource): OkHttpClient =
            TunesApiFactory.httpClient(configSource)

        @Provides
        @Singleton
        fun tunesApi(
            @TunesHttpClient client: OkHttpClient,
            configSource: ServerConfigSource,
            clock: Clock
        ): TunesApi = TunesApiFactory.create(client, configSource, clock)
    }

    /** The player's singletons, like PlayerModule's, in a scratch folder (see the class doc). */
    @Module
    @InstallIn(SingletonComponent::class)
    object ScratchPlayerModule {
        @Provides
        @Singleton
        fun databaseProvider(@ApplicationContext context: Context): DatabaseProvider =
            Scratch.of(context).database

        @Provides
        @Singleton
        fun mediaCaches(@ApplicationContext context: Context): MediaCaches =
            Scratch.of(context).caches

        @Provides
        @Singleton
        fun mediaDataSources(
            @TunesHttpClient client: OkHttpClient,
            caches: MediaCaches
        ): MediaDataSources = MediaDataSources(client, caches)

        @Provides
        @Singleton
        fun offlineSelection(@ApplicationContext context: Context): OfflineSelectionStore =
            Scratch.of(context).selection

        @Provides
        fun offlineSyncer(
            api: TunesApi,
            store: OfflineSelectionStore,
            downloads: OfflineDownloads,
            settings: PlayerSettingsSource
        ): OfflineSyncer = OfflineSyncer(api, store, downloads, settings)
    }

    @Before
    fun setUp() {
        assumeTrue(
            "Run with -e screenshots true",
            InstrumentationRegistry.getArguments().getString("screenshots") == "true"
        )
        assumeTrue(Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
        hilt.inject()
        val config = runBlocking { demo.start() }
        configSource.set(checkNotNull(config) { "The demo server did not start" })
    }

    @After
    fun tearDown() {
        scenario?.close()
        resetAppSettings()
        Scratch.discard()
    }

    /**
     * One test for the four tours: Coil's image loader is set once per process, with the client
     * of the first test's graph, so later graphs (and their demo servers) would show no covers.
     */
    @Test
    fun storeScreenshots() {
        for (locale in listOf(Locale.US, Locale.forLanguageTag("es-ES"))) {
            for (dark in listOf(false, true)) {
                tour(locale, dark)
                scenario?.close()
                scenario = null
            }
        }
    }

    /** Listen Now, Radio, Library, Search, an album, the full player and its lyrics. */
    private fun tour(locale: Locale, dark: Boolean) {
        context.getSystemService(LocaleManager::class.java).applicationLocales =
            LocaleList(locale)
        context.getSystemService(UiModeManager::class.java).setApplicationNightMode(
            if (dark) UiModeManager.MODE_NIGHT_YES else UiModeManager.MODE_NIGHT_NO
        )
        index = if (dark) DARK_FIRST else 0
        val folder = File(context.filesDir, "screenshots/${locale.toLanguageTag()}")
        scenario = ActivityScenario.launch(MainActivity::class.java)

        waitFor(hasTestTag(LISTEN_NOW_LIST_TAG))
        waitFor(hasText("Neon Tide"))
        shoot(folder, "listen_now", dark)

        compose.onNodeWithTag(Tab.RADIO.testTag).performClick()
        waitFor(hasText("Late-Night Jazz"))
        shoot(folder, "radio", dark)

        compose.onNodeWithTag(Tab.LIBRARY.testTag).performClick()
        waitFor(hasTestTag(TITLE_TAG) and hasText(text(R.string.tab_library)))
        shoot(folder, "library", dark)

        compose.onNodeWithTag(Tab.SEARCH.testTag).performClick()
        compose.onNodeWithTag(SEARCH_FIELD_TAG).performTextInput("nova")
        val album = "Neon Tide, Nova Kestrel"
        waitFor(hasContentDescription(album))
        hideKeyboard()
        shoot(folder, "search", dark)

        compose.onNodeWithContentDescription(album).performClick()
        waitFor(hasTestTag(ALBUM_LIST_TAG))
        val song = text(R.string.track_description, "Afterglow Avenue", "Nova Kestrel")
        waitFor(hasContentDescription(song))
        shoot(folder, "album", dark)

        compose.onNodeWithContentDescription(song).performClick()
        waitFor(hasTestTag(MINI_PLAYER_TAG))
        compose.onNodeWithTag(MINI_PLAYER_TAG).performClick()
        waitFor(hasTestTag(FULL_PLAYER_TAG))
        waitFor(hasContentDescription(text(R.string.player_pause)))
        shoot(folder, "player", dark)

        compose.onNodeWithTag(LYRICS_BUTTON_TAG).performClick()
        waitFor(hasTestTag(LYRICS_TAG))
        waitFor(hasTestTag(LYRICS_ACTIVE_LINE_TAG))
        shoot(folder, "lyrics", dark)

        // Quiet again (the demo plays a soft chord), and no mini player in the next tour.
        playback.clear()
        runBlocking { withTimeout(TIMEOUT_MS) { playback.state.first { it.queue.isEmpty() } } }
    }

    private fun resetAppSettings() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.getSystemService(LocaleManager::class.java).applicationLocales =
                LocaleList.getEmptyLocaleList()
            context.getSystemService(UiModeManager::class.java)
                .setApplicationNightMode(UiModeManager.MODE_NIGHT_AUTO)
        }
    }

    /** A string in the app's current language (the activity's, not the test's). */
    private fun text(@StringRes id: Int, vararg args: Any): String {
        var value = ""
        checkNotNull(scenario).onActivity { value = it.getString(id, *args) }
        return value
    }

    private fun hideKeyboard() {
        checkNotNull(scenario).onActivity {
            WindowCompat.getInsetsController(it.window, it.window.decorView)
                .hide(WindowInsetsCompat.Type.ime())
        }
    }

    private fun waitFor(matcher: SemanticsMatcher) {
        compose.waitUntil(TIMEOUT_MS) {
            compose.onAllNodes(matcher, useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty()
        }
    }

    /** Saves the app's window (no system bars, so nothing of the phone shows) as a PNG. */
    private fun shoot(folder: File, name: String, dark: Boolean) {
        // Covers load and animations settle outside Compose's idling.
        SystemClock.sleep(SETTLE_MS)
        compose.waitForIdle()
        val bitmap = compose.onRoot().captureToImage().asAndroidBitmap()
        index++
        val theme = if (dark) "dark" else "light"
        folder.mkdirs()
        File(folder, "%02d_%s_%s.png".format(Locale.ROOT, index, name, theme)).outputStream()
            .use { bitmap.compress(Bitmap.CompressFormat.PNG, PNG_QUALITY, it) }
    }

    /** The scratch player storage, once per process like PlayerModule's (one SimpleCache each). */
    private class Scratch(context: Context) {
        val root = File(context.cacheDir, "screenshots-player").apply {
            deleteRecursively()
            mkdirs()
        }
        val database = ScratchDatabase(context, File(root, "media.db").path)
        private val evictor = AdjustableLruEvictor(CachePolicy.maxBytes(CACHE_MB))
        val caches = MediaCaches(
            play = SimpleCache(File(root, "play"), evictor, database),
            evictor = evictor,
            downloads = SimpleCache(File(root, "offline"), NoOpCacheEvictor(), database)
        )
        val selection = DataStoreOfflineSelection(
            PreferenceDataStoreFactory.create { File(root, "offline.preferences_pb") }
        )

        /** Closes the caches and deletes the folder (the playback was cleared by then). */
        fun close() {
            (caches.play as SimpleCache).release()
            (caches.downloads as SimpleCache).release()
            database.close()
            root.deleteRecursively()
        }

        companion object {
            private var instance: Scratch? = null

            @Synchronized
            fun of(context: Context): Scratch =
                instance ?: Scratch(context.applicationContext).also { instance = it }

            /** Deletes the scratch folder of this run, if one was made. */
            @Synchronized
            fun discard() {
                instance?.close()
                instance = null
            }
        }
    }

    /** Media3's index database in the scratch folder, not the app's own database. */
    private class ScratchDatabase(context: Context, path: String) :
        SQLiteOpenHelper(context, path, null, 1),
        DatabaseProvider {
        override fun onCreate(db: SQLiteDatabase) = Unit

        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
    }

    private companion object {
        const val TIMEOUT_MS = 20_000L
        const val SETTLE_MS = 2_000L
        const val DARK_FIRST = 7
        const val CACHE_MB = 64
        const val PNG_QUALITY = 100
    }
}
