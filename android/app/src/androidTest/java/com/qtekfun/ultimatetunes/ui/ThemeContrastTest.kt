// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.toPixelMap
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithText
import androidx.test.platform.app.InstrumentationRegistry
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.connect.ConnectScreen
import com.qtekfun.ultimatetunes.ui.connect.ConnectUiState
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.listennow.ListenNowScreen
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.navigation.AppRoot
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Text must stay readable in both themes: the title of each screen is drawn in a colour that
 * contrasts with the background (catches text left in the default black on a dark background).
 */
@HiltAndroidTest
class ThemeContrastTest {
    @get:Rule(order = 0)
    val hilt = HiltAndroidRule(this)

    @get:Rule(order = 1)
    val compose = createComposeRule()

    private fun text(id: Int) =
        InstrumentationRegistry.getInstrumentation().targetContext.getString(id)

    /**
     * True if the node showing [label] contains text that stands out from its background: the
     * contrast ratio between its lightest and darkest pixels is at least [MIN_CONTRAST] (WCAG
     * large text). Text in the background's own colour gives 1:1.
     */
    private fun hasReadablePixels(label: String): Boolean {
        val pixels = compose.onAllNodesWithText(label).onFirst().captureToImage().toPixelMap()
        val luminances = (0 until pixels.width).flatMap { x ->
            (0 until pixels.height).map { y -> pixels[x, y].luminance() }
        }
        val contrast = (luminances.max() + FLARE) / (luminances.min() + FLARE)
        return contrast >= MIN_CONTRAST
    }

    private fun check(dark: Boolean, label: String, content: @Composable () -> Unit) {
        compose.setContent { UltimateTunesTheme(darkTheme = dark) { content() } }
        assertTrue("'$label' unreadable (dark=$dark)", hasReadablePixels(label))
    }

    @Test
    fun connectTitleIsReadableInDarkTheme() {
        check(dark = true, text(R.string.connect_title)) {
            ConnectScreen(ConnectUiState(), {}, {}, {})
        }
    }

    @Test
    fun connectTitleIsReadableInLightTheme() {
        check(dark = false, text(R.string.connect_title)) {
            ConnectScreen(ConnectUiState(), {}, {}, {})
        }
    }

    @Test
    fun largeTitleIsReadableInDarkTheme() {
        check(dark = true, text(R.string.tab_listen_now)) {
            ListenNowScreen(
                state = LoadState.Loading,
                recommendations = null,
                contentPadding = PaddingValues(),
                onRetry = {},
                onPlay = { _, _ -> },
                onOpenStation = {},
                onOpenCharts = {}
            )
        }
    }

    @Test
    fun errorMessageIsReadableInDarkTheme() {
        check(dark = true, text(R.string.error_network)) {
            androidx.compose.material3.Surface(color = Color.Black) {
                ErrorState(LoadError.NETWORK, onRetry = {})
            }
        }
    }

    private companion object {
        const val MIN_CONTRAST = 3f
        const val FLARE = 0.05f
    }
}
