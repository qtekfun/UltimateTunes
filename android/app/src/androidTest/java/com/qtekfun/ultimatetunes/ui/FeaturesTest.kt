// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.annotation.StringRes
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createEmptyComposeRule
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTouchInput
import androidx.core.content.ContextCompat
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.actions.COLLECTION_OFFLINE_TAG
import com.qtekfun.ultimatetunes.ui.actions.PLAYLIST_PICKER_TAG
import com.qtekfun.ultimatetunes.ui.actions.TRACK_MENU_TAG
import com.qtekfun.ultimatetunes.ui.actions.TrackMenuItem
import com.qtekfun.ultimatetunes.ui.album.ALBUM_MENU_TAG
import com.qtekfun.ultimatetunes.ui.designsystem.TITLE_TAG
import com.qtekfun.ultimatetunes.ui.navigation.NOTIFICATIONS_DIALOG_TAG
import com.qtekfun.ultimatetunes.ui.navigation.Tab
import com.qtekfun.ultimatetunes.ui.player.FULL_PLAYER_TAG
import com.qtekfun.ultimatetunes.ui.player.MINI_PLAYER_TAG
import com.qtekfun.ultimatetunes.ui.player.PLAYER_MORE_TAG
import com.qtekfun.ultimatetunes.ui.player.PLAYER_RADIO_TAG
import com.qtekfun.ultimatetunes.ui.search.SEARCH_FIELD_TAG
import com.qtekfun.ultimatetunes.ui.settings.AppPrefsStore
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import javax.inject.Inject
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/** The PLAN T18 flows against [FakeTunesApi]: song menus, playlists, favourites, offline. */
@HiltAndroidTest
class FeaturesTest {
    @get:Rule(order = 0)
    val hilt = HiltAndroidRule(this)

    @get:Rule(order = 1)
    val compose = createEmptyComposeRule()

    @Inject
    lateinit var configSource: InMemoryServerConfigSource

    @Inject
    lateinit var api: TunesApi

    @Inject
    lateinit var prefs: AppPrefsStore

    private var scenario: ActivityScenario<MainActivity>? = null
    private val fake get() = api as FakeTunesApi

    @Before
    fun inject() {
        hilt.inject()
        configSource.set(FakeTunesApi.config)
    }

    private fun launch() {
        scenario = ActivityScenario.launch(MainActivity::class.java)
    }

    @After
    fun close() {
        scenario?.close()
    }

    private fun text(@StringRes id: Int, vararg args: Any): String =
        InstrumentationRegistry.getInstrumentation().targetContext.getString(id, *args)

    private fun waitFor(matcher: SemanticsMatcher) {
        compose.waitUntil(TIMEOUT_MS) {
            compose.onAllNodes(matcher, useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty()
        }
    }

    private fun waitGone(matcher: SemanticsMatcher) {
        compose.waitUntil(TIMEOUT_MS) {
            compose.onAllNodes(matcher, useUnmergedTree = true).fetchSemanticsNodes().isEmpty()
        }
    }

    private val tidewater get() = text(
        R.string.track_description,
        "Tidewater",
        "The Paper Lanterns"
    )

    /** Opens Harbour Lights from Search. */
    private fun openAlbum() {
        compose.onNodeWithTag(Tab.SEARCH.testTag).performClick()
        compose.onNodeWithTag(SEARCH_FIELD_TAG).performTextInput("lanterns")
        val album = "Harbour Lights, The Paper Lanterns"
        waitFor(hasContentDescription(album))
        compose.onNodeWithContentDescription(album).performClick()
        waitFor(hasTestTag(TITLE_TAG) and hasText("Harbour Lights"))
        waitFor(hasContentDescription(tidewater))
    }

    private fun longPressTidewater() {
        compose.onNodeWithContentDescription(tidewater).performTouchInput { longClick() }
        waitFor(hasTestTag(TRACK_MENU_TAG))
    }

    @Test
    fun aLongPressAddsASongToAPlaylist() {
        launch()
        openAlbum()
        longPressTidewater()

        compose.onNodeWithTag(TrackMenuItem.ADD_TO_PLAYLIST.tag).performClick()
        waitFor(hasTestTag(PLAYLIST_PICKER_TAG))
        val sunday = hasContentDescription(FakeTunesApi.SUNDAY, substring = true) and
            hasAnyAncestor(hasTestTag(PLAYLIST_PICKER_TAG))
        waitFor(sunday)
        compose.onNode(sunday).performClick()

        val added = InstrumentationRegistry.getInstrumentation().targetContext.resources
            .getQuantityString(R.plurals.event_added_to_playlist, 1, 1, FakeTunesApi.SUNDAY)
        waitFor(hasText(added))
        assertEquals(listOf("Tidewater"), fake.playlistSongs(FakeTunesApi.SUNDAY).takeLast(1))
    }

    @Test
    fun aLongPressStarsASongAndOffersTheAlbumAndAStation() {
        launch()
        openAlbum()
        longPressTidewater()
        waitFor(hasTestTag(TrackMenuItem.GO_TO_ALBUM.tag))
        waitFor(hasTestTag(TrackMenuItem.START_STATION.tag))

        compose.onNodeWithTag(TrackMenuItem.FAVOURITE.tag).performClick()

        waitGone(hasTestTag(TRACK_MENU_TAG))
        compose.waitUntil(TIMEOUT_MS) { SongId("song-2") in fake.starredSongIds }
        longPressTidewater()
        waitFor(hasText(text(R.string.favourite_remove)))
    }

    @Test
    fun anAlbumIsKeptOfflineFromItsMenu() {
        launch()
        openAlbum()

        compose.onNodeWithTag(ALBUM_MENU_TAG).performClick()
        compose.onNodeWithTag(COLLECTION_OFFLINE_TAG).performClick()
        waitFor(hasText(text(R.string.collection_offline)))

        // Back as it was: the phone's real offline selection must not keep the test album.
        compose.onNodeWithTag(ALBUM_MENU_TAG).performClick()
        compose.onNodeWithText(text(R.string.collection_stop_offline)).performClick()
        waitGone(hasText(text(R.string.collection_offline)))
    }

    @Test
    fun theFullPlayerOffersTheSongMenuAndARadio() {
        launch()
        openAlbum()
        compose.onNodeWithContentDescription(tidewater).performClick()
        waitFor(hasTestTag(MINI_PLAYER_TAG))
        compose.onNodeWithTag(MINI_PLAYER_TAG).performClick()
        waitFor(hasTestTag(FULL_PLAYER_TAG))

        waitFor(hasTestTag(PLAYER_RADIO_TAG))
        compose.onNodeWithTag(PLAYER_MORE_TAG).performClick()
        waitFor(hasTestTag(TRACK_MENU_TAG))
        waitFor(hasText("Tidewater"))
    }

    @Test
    fun theNotificationQuestionIsAskedOnceWithItsReason() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assumeTrue(Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
        assumeTrue(
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED
        )
        runBlocking { prefs.setNotificationsAsked(false) }
        launch()

        waitFor(hasTestTag(NOTIFICATIONS_DIALOG_TAG))
        waitFor(hasText(text(R.string.notifications_rationale)))
        compose.onNodeWithText(text(R.string.notifications_not_now)).performClick()

        waitGone(hasTestTag(NOTIFICATIONS_DIALOG_TAG))
        assertTrue(runBlocking { (prefs as MemoryAppPrefs).notificationsAsked.value })
    }

    private companion object {
        const val TIMEOUT_MS = 10_000L
    }
}
