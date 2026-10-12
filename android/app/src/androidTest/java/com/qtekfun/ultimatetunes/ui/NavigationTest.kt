// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import androidx.annotation.StringRes
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.ui.connect.CONNECT_API_KEY_TAG
import com.qtekfun.ultimatetunes.ui.connect.CONNECT_BUTTON_TAG
import com.qtekfun.ultimatetunes.ui.connect.CONNECT_SERVER_URL_TAG
import com.qtekfun.ultimatetunes.ui.designsystem.TITLE_TAG
import com.qtekfun.ultimatetunes.ui.navigation.Tab
import com.qtekfun.ultimatetunes.ui.player.FULL_PLAYER_TAG
import com.qtekfun.ultimatetunes.ui.player.MINI_PLAYER_TAG
import com.qtekfun.ultimatetunes.ui.radio.STATION_PLAY_TAG
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import javax.inject.Inject
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/** Navigation of the app shell (PLAN T12) against [FakeTunesApi]. */
@HiltAndroidTest
class NavigationTest {
    @get:Rule(order = 0)
    val hilt = HiltAndroidRule(this)

    @get:Rule(order = 1)
    val compose = createEmptyComposeRule()

    @Inject
    lateinit var configSource: InMemoryServerConfigSource

    private var scenario: ActivityScenario<MainActivity>? = null

    @Before
    fun inject() {
        hilt.inject()
    }

    @After
    fun close() {
        scenario?.close()
    }

    private fun text(@StringRes id: Int, vararg args: Any): String =
        InstrumentationRegistry.getInstrumentation().targetContext.getString(id, *args)

    private fun launch(connected: Boolean) {
        if (connected) configSource.set(FakeTunesApi.config)
        scenario = ActivityScenario.launch(MainActivity::class.java)
    }

    private fun waitFor(matcher: SemanticsMatcher) {
        compose.waitUntil(TIMEOUT_MS) {
            compose.onAllNodes(matcher, useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty()
        }
    }

    private fun assertTitle(@StringRes id: Int) {
        val matcher = hasTestTag(TITLE_TAG) and hasText(text(id))
        waitFor(matcher)
    }

    @Test
    fun connectingWithAWorkingKeyOpensListenNow() {
        launch(connected = false)

        compose.onNodeWithTag(CONNECT_SERVER_URL_TAG).performTextInput("music.example.net")
        compose.onNodeWithTag(CONNECT_API_KEY_TAG).performTextInput(FakeTunesApi.API_KEY)
        compose.onNodeWithTag(CONNECT_BUTTON_TAG).performClick()

        assertTitle(R.string.tab_listen_now)
        waitFor(hasText(text(R.string.listen_now_recently_played)))
    }

    @Test
    fun aRefusedKeyStaysOnConnectWithTheReason() {
        launch(connected = false)

        compose.onNodeWithTag(CONNECT_SERVER_URL_TAG).performTextInput("music.example.net")
        compose.onNodeWithTag(CONNECT_API_KEY_TAG).performTextInput("utk_" + "Z".repeat(43))
        compose.onNodeWithTag(CONNECT_BUTTON_TAG).performClick()

        waitFor(hasText(text(R.string.connect_error_key_refused)))
        compose.onNodeWithTag(CONNECT_BUTTON_TAG).assertIsDisplayed()
    }

    @Test
    fun aKeyRefusedLaterLeadsBackToConnect() {
        configSource.set(
            ServerConfig(FakeTunesApi.config.baseUrl, ApiKeySecret("utk_" + "Y".repeat(43)))
        )
        scenario = ActivityScenario.launch(MainActivity::class.java)

        waitFor(hasText(text(R.string.error_unauthorized)))
        compose.onNodeWithText(text(R.string.connect_again)).performClick()

        waitFor(hasTestTag(CONNECT_BUTTON_TAG))
    }

    @Test
    fun theTabsSwitchBetweenTheFourScreens() {
        launch(connected = true)
        assertTitle(R.string.tab_listen_now)

        compose.onNodeWithTag(Tab.RADIO.testTag).performClick()
        assertTitle(R.string.tab_radio)
        waitFor(hasText(text(R.string.radio_from_songs)))

        compose.onNodeWithTag(Tab.LIBRARY.testTag).performClick()
        assertTitle(R.string.tab_library)

        compose.onNodeWithTag(Tab.SEARCH.testTag).performClick()
        assertTitle(R.string.tab_search)

        compose.onNodeWithTag(Tab.LISTEN_NOW.testTag).performClick()
        assertTitle(R.string.tab_listen_now)
    }

    @Test
    fun aStationPlaysIntoTheMiniPlayerWhichOpensTheFullPlayer() {
        launch(connected = true)
        compose.onNodeWithTag(Tab.RADIO.testTag).performClick()
        val station = text(R.string.station_description, FakeTunesApi.KEEPER_RADIO)
        waitFor(hasContentDescription(station))

        compose.onNodeWithContentDescription(station).performClick()
        waitFor(hasTestTag(STATION_PLAY_TAG))
        compose.onNodeWithTag(STATION_PLAY_TAG).performClick()

        waitFor(hasTestTag(MINI_PLAYER_TAG))
        compose.onNodeWithTag(MINI_PLAYER_TAG).performClick()

        waitFor(hasTestTag(FULL_PLAYER_TAG))
        // The real player (PLAN T18) has no audio from the fake API: its play/pause button shows
        // whichever state the session reports; it must be there and answer.
        val toggle = hasAnyAncestor(hasTestTag(FULL_PLAYER_TAG)) and (
            hasContentDescription(text(R.string.player_play)) or
                hasContentDescription(text(R.string.player_pause))
            )
        waitFor(toggle)
        compose.onNode(toggle).assertIsDisplayed().performClick()

        compose.onNodeWithContentDescription(text(R.string.player_close)).performClick()
        waitFor(hasTestTag(MINI_PLAYER_TAG))
        compose.waitUntil(TIMEOUT_MS) {
            compose.onAllNodes(hasTestTag(FULL_PLAYER_TAG)).fetchSemanticsNodes().isEmpty()
        }
    }

    @Test
    fun aStationOpensInsideListenNowAndBackReturns() {
        launch(connected = true)
        val station = text(R.string.station_description, FakeTunesApi.KEEPER_RADIO)
        waitFor(hasText(text(R.string.listen_now_stations)))

        compose.onNodeWithContentDescription(station).performClick()
        waitFor(hasTestTag(STATION_PLAY_TAG))
        compose.onNodeWithText(text(R.string.station_up_next)).assertIsDisplayed()

        compose.onNodeWithContentDescription(text(R.string.back)).performClick()
        assertTitle(R.string.tab_listen_now)
    }

    private companion object {
        const val TIMEOUT_MS = 5_000L
    }
}
