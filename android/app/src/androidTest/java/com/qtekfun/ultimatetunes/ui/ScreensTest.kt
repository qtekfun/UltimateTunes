// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import androidx.annotation.StringRes
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTextReplacement
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.ui.charts.CHARTS_LIST_TAG
import com.qtekfun.ultimatetunes.ui.connect.CONNECT_API_KEY_TAG
import com.qtekfun.ultimatetunes.ui.connect.CONNECT_BUTTON_TAG
import com.qtekfun.ultimatetunes.ui.connect.CONNECT_METHOD_KEY_TAG
import com.qtekfun.ultimatetunes.ui.connect.CONNECT_SERVER_URL_TAG
import com.qtekfun.ultimatetunes.ui.designsystem.DIALOG_CONFIRM_TAG
import com.qtekfun.ultimatetunes.ui.designsystem.DIALOG_FIELD_TAG
import com.qtekfun.ultimatetunes.ui.designsystem.PLAY_BUTTON_TAG
import com.qtekfun.ultimatetunes.ui.designsystem.TITLE_TAG
import com.qtekfun.ultimatetunes.ui.homescreen.HOME_CHARTS_TAG
import com.qtekfun.ultimatetunes.ui.homescreen.HOME_LIST_TAG
import com.qtekfun.ultimatetunes.ui.imports.IMPORT_PROGRESS_TAG
import com.qtekfun.ultimatetunes.ui.imports.IMPORT_URL_BUTTON_TAG
import com.qtekfun.ultimatetunes.ui.imports.IMPORT_URL_TAG
import com.qtekfun.ultimatetunes.ui.library.LIBRARY_IMPORT_TAG
import com.qtekfun.ultimatetunes.ui.library.LIBRARY_NEW_TAG
import com.qtekfun.ultimatetunes.ui.library.LibraryFilter
import com.qtekfun.ultimatetunes.ui.library.NEW_PLAYLIST_TAG
import com.qtekfun.ultimatetunes.ui.library.libraryFilterTag
import com.qtekfun.ultimatetunes.ui.lyrics.LYRICS_ACTIVE_LINE_TAG
import com.qtekfun.ultimatetunes.ui.navigation.Tab
import com.qtekfun.ultimatetunes.ui.player.FULL_PLAYER_TAG
import com.qtekfun.ultimatetunes.ui.player.LYRICS_BUTTON_TAG
import com.qtekfun.ultimatetunes.ui.player.MINI_PLAYER_TAG
import com.qtekfun.ultimatetunes.ui.playlists.PLAYLIST_MENU_TAG
import com.qtekfun.ultimatetunes.ui.search.SEARCH_FIELD_TAG
import com.qtekfun.ultimatetunes.ui.settings.SETTINGS_DISCONNECT_TAG
import com.qtekfun.ultimatetunes.ui.settings.SETTINGS_LIST_TAG
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import javax.inject.Inject
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/** The T13 screens against [FakeTunesApi]: search, albums, playlists, lyrics, import, settings. */
@HiltAndroidTest
class ScreensTest {
    @get:Rule(order = 0)
    val hilt = HiltAndroidRule(this)

    @get:Rule(order = 1)
    val compose = createEmptyComposeRule()

    @Inject
    lateinit var configSource: InMemoryServerConfigSource

    private var scenario: ActivityScenario<MainActivity>? = null

    @Before
    fun launch() {
        hilt.inject()
        configSource.set(FakeTunesApi.config)
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

    private fun assertTitle(title: String) = waitFor(hasTestTag(TITLE_TAG) and hasText(title))

    private fun openLibrary() {
        compose.onNodeWithTag(Tab.LIBRARY.testTag).performClick()
        assertTitle(text(R.string.tab_library))
    }

    private val sundayRow = hasContentDescription(FakeTunesApi.SUNDAY + ",", substring = true)

    @Test
    fun homeShowsRecommendationsAndOpensCharts() {
        // Home is the start tab.
        waitFor(hasText(text(R.string.home_stations)))

        compose.onNodeWithTag(HOME_LIST_TAG)
            .performScrollToNode(hasText(text(R.string.home_recommended)))
        compose.onNodeWithTag(HOME_LIST_TAG).performScrollToNode(hasTestTag(HOME_CHARTS_TAG))
        compose.onNodeWithTag(HOME_CHARTS_TAG).performClick()

        assertTitle(text(R.string.charts_title))
        waitFor(hasTestTag(CHARTS_LIST_TAG))
    }

    @Test
    fun theLibraryFiltersShowItsContentDirectly() {
        openLibrary()
        waitFor(sundayRow)

        compose.onNodeWithTag(libraryFilterTag(LibraryFilter.ALBUMS)).performClick()
        waitFor(
            hasContentDescription(
                text(R.string.album_description, "Harbour Lights", "The Paper Lanterns")
            )
        )
        compose.onNodeWithTag(libraryFilterTag(LibraryFilter.ARTISTS)).performClick()
        waitFor(hasContentDescription("Marisol Vega"))
        compose.onNodeWithTag(libraryFilterTag(LibraryFilter.SONGS)).performClick()
        waitFor(
            hasContentDescription(
                text(R.string.track_description, "Tidewater", "The Paper Lanterns")
            )
        )
    }

    @Test
    fun searchOpensAnAlbumWhoseSongsPlay() {
        compose.onNodeWithTag(Tab.SEARCH.testTag).performClick()
        compose.onNodeWithTag(SEARCH_FIELD_TAG).performTextInput("lanterns")

        val album = "Harbour Lights, The Paper Lanterns"
        waitFor(hasContentDescription(album))
        // The YouTube Music album is marked as not in the library yet.
        waitFor(
            hasContentDescription(
                "Lanterns at Dusk, The Paper Lanterns, " + text(R.string.not_in_library)
            )
        )
        compose.onNodeWithContentDescription(album).performClick()

        assertTitle("Harbour Lights")
        waitFor(hasTestTag(PLAY_BUTTON_TAG))
        compose.onNodeWithContentDescription(
            text(R.string.track_description, "Tidewater", "The Paper Lanterns")
        ).performClick()

        waitFor(hasTestTag(MINI_PLAYER_TAG))
        waitFor(hasText("Tidewater"))
    }

    @Test
    fun anExternalAlbumFromSearchSaysItIsNotInTheLibrary() {
        compose.onNodeWithTag(Tab.SEARCH.testTag).performClick()
        compose.onNodeWithTag(SEARCH_FIELD_TAG).performTextInput("dusk")
        val external = "Lanterns at Dusk, The Paper Lanterns, " + text(R.string.not_in_library)
        waitFor(hasContentDescription(external))

        compose.onNodeWithContentDescription(external).performClick()

        assertTitle("Lanterns at Dusk")
        waitFor(hasText(text(R.string.album_external)))
        compose.onNodeWithContentDescription(text(R.string.back)).performClick()
        waitFor(hasTestTag(SEARCH_FIELD_TAG))
    }

    @Test
    fun aPlaylistIsCreatedRenamedAndDeleted() {
        openLibrary()
        waitFor(hasText(FakeTunesApi.SUNDAY))

        compose.onNodeWithTag(LIBRARY_NEW_TAG).performClick()
        compose.onNodeWithTag(NEW_PLAYLIST_TAG).performClick()
        compose.onNodeWithTag(DIALOG_FIELD_TAG).performTextInput("Morning Run")
        compose.onNodeWithTag(DIALOG_CONFIRM_TAG).performClick()

        assertTitle("Morning Run")
        waitFor(hasText(text(R.string.playlist_empty)))

        compose.onNodeWithTag(PLAYLIST_MENU_TAG).performClick()
        compose.onNodeWithText(text(R.string.playlist_rename)).performClick()
        compose.onNodeWithTag(DIALOG_FIELD_TAG).performTextReplacement("Evening Walk")
        compose.onNodeWithTag(DIALOG_CONFIRM_TAG).performClick()
        assertTitle("Evening Walk")

        compose.onNodeWithTag(PLAYLIST_MENU_TAG).performClick()
        compose.onNodeWithText(text(R.string.playlist_delete)).performClick()
        compose.onNodeWithTag(DIALOG_CONFIRM_TAG).performClick()

        assertTitle(text(R.string.tab_library))
        waitFor(hasText(FakeTunesApi.SUNDAY))
        waitGone(hasText("Evening Walk"))
    }

    @Test
    fun lyricsFollowTheSongInThePlayer() {
        openLibrary()
        waitFor(sundayRow)
        compose.onNode(sundayRow).performClick()
        waitFor(hasTestTag(PLAY_BUTTON_TAG))
        compose.onNodeWithTag(PLAY_BUTTON_TAG).performClick()

        waitFor(hasTestTag(MINI_PLAYER_TAG))
        compose.onNodeWithTag(MINI_PLAYER_TAG).performClick()
        waitFor(hasTestTag(FULL_PLAYER_TAG))
        compose.onNodeWithTag(LYRICS_BUTTON_TAG).performClick()

        // At 0:00 the first line is the one being sung.
        waitFor(hasTestTag(LYRICS_ACTIVE_LINE_TAG) and hasText(FakeTunesApi.LYRIC_FIRST))
    }

    @Test
    fun aLinkImportShowsItsReportAndOpensThePlaylist() {
        openLibrary()
        compose.onNodeWithTag(LIBRARY_NEW_TAG).performClick()
        compose.onNodeWithTag(LIBRARY_IMPORT_TAG).performClick()
        assertTitle(text(R.string.import_title))

        compose.onNodeWithTag(IMPORT_URL_TAG)
            .performTextInput("https://music.youtube.com/playlist?list=PLexample")
        compose.onNodeWithTag(IMPORT_URL_BUTTON_TAG).performClick()

        waitFor(hasTestTag(IMPORT_PROGRESS_TAG))
        waitFor(hasText(text(R.string.import_state_done)))
        waitFor(hasText(text(R.string.import_counts, 1, 2, 1)))
        compose.onNodeWithText(text(R.string.import_open_playlist)).performClick()

        assertTitle(FakeTunesApi.SUNDAY)
    }

    @Test
    fun settingsRevokeAnotherKeyAndDisconnectToACleanConnectScreen() {
        openSettings()
        scrollSettingsTo(hasText(FakeTunesApi.TABLET_KEY))
        scrollSettingsTo(hasText(text(R.string.settings_key_this_device)))

        scrollSettingsTo(hasText(text(R.string.settings_revoke)))
        compose.onNodeWithText(text(R.string.settings_revoke)).performClick()
        compose.onNodeWithTag(DIALOG_CONFIRM_TAG).performClick()
        waitGone(hasText(FakeTunesApi.TABLET_KEY))

        disconnect()

        // Connect again by hand, then disconnect: the form must not keep what was typed.
        compose.onNodeWithTag(CONNECT_SERVER_URL_TAG).performTextInput("music.example.net")
        compose.onNodeWithTag(CONNECT_METHOD_KEY_TAG).performClick()
        compose.onNodeWithTag(CONNECT_API_KEY_TAG).performTextInput(FakeTunesApi.API_KEY)
        compose.onNodeWithTag(CONNECT_BUTTON_TAG).performClick()
        assertTitle(text(R.string.tab_home))
        openSettings()
        disconnect()
        compose.onNodeWithTag(CONNECT_SERVER_URL_TAG).assert(hasText("music.example.net").not())
    }

    private fun openSettings() {
        compose.onNodeWithContentDescription(text(R.string.settings_title)).performClick()
        assertTitle(text(R.string.settings_title))
    }

    private fun scrollSettingsTo(matcher: SemanticsMatcher) {
        waitFor(hasTestTag(SETTINGS_LIST_TAG))
        compose.waitUntil(TIMEOUT_MS) {
            runCatching {
                compose.onNodeWithTag(SETTINGS_LIST_TAG).performScrollToNode(matcher)
            }.isSuccess
        }
    }

    private fun disconnect() {
        scrollSettingsTo(hasTestTag(SETTINGS_DISCONNECT_TAG))
        compose.onNodeWithTag(SETTINGS_DISCONNECT_TAG).performClick()
        compose.onNodeWithTag(DIALOG_CONFIRM_TAG).performClick()
        waitFor(hasTestTag(CONNECT_BUTTON_TAG))
    }

    private companion object {
        const val TIMEOUT_MS = 5_000L
    }
}
