// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import android.app.Activity
import android.app.ActivityManager
import android.content.Intent
import android.net.Uri
import androidx.annotation.StringRes
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isEnabled
import androidx.compose.ui.test.junit4.v2.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.ui.connect.CONNECT_LINK_CANCEL_TAG
import com.qtekfun.ultimatetunes.ui.connect.CONNECT_LINK_CONFIRM_TAG
import com.qtekfun.ultimatetunes.ui.connect.CONNECT_LINK_DIALOG_TAG
import com.qtekfun.ultimatetunes.ui.connect.CONNECT_SERVER_URL_TAG
import com.qtekfun.ultimatetunes.ui.designsystem.TITLE_TAG
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import java.net.URLEncoder
import javax.inject.Inject
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * The admin panel's QR code, opened by the camera app as an `ultimatetunes://connect` link:
 * ConnectLinkActivity hands it over and MainActivity asks, connecting only on confirmation. The
 * configuration lives in memory ([FakeTunesApiModule]); the app's saved connection is untouched.
 */
@HiltAndroidTest
class ConnectLinkTest {
    @get:Rule(order = 0)
    val hilt = HiltAndroidRule(this)

    @get:Rule(order = 1)
    val compose = createEmptyComposeRule()

    @Inject
    lateinit var configSource: InMemoryServerConfigSource

    private var scenario: ActivityScenario<MainActivity>? = null

    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    @Before
    fun inject() {
        hilt.inject()
    }

    @After
    fun close() {
        scenario?.close()
        instrumentation.runOnMainSync {
            Stage.entries.filter { it != Stage.DESTROYED }
                .flatMap { ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(it) }
                .forEach(Activity::finish)
        }
    }

    private fun text(@StringRes id: Int, vararg args: Any): String = context.getString(id, *args)

    private fun encode(value: String) = URLEncoder.encode(value, "UTF-8")

    /** The intent the camera app sends: implicit, resolved by the app's intent filter. */
    private fun linkIntent(link: String): Intent =
        Intent(Intent.ACTION_VIEW, Uri.parse(link)).setPackage(context.packageName)

    private fun connectLink(key: String = FakeTunesApi.API_KEY) =
        "ultimatetunes://connect?url=${encode(SERVER)}&key=${encode(key)}"

    /** As a camera app that starts links in a new task. */
    private fun launchWithLink(link: String = connectLink()) {
        context.startActivity(linkIntent(link).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    private fun waitFor(matcher: SemanticsMatcher) {
        compose.waitUntil(TIMEOUT_MS) {
            compose.onAllNodes(matcher, useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty()
        }
    }

    private fun waitForNo(matcher: SemanticsMatcher) {
        compose.waitUntil(TIMEOUT_MS) {
            compose.onAllNodes(matcher, useUnmergedTree = true).fetchSemanticsNodes().isEmpty()
        }
    }

    /** Connect is enabled only once the dialog has been on screen for a moment. */
    private fun confirm() {
        waitFor(hasTestTag(CONNECT_LINK_CONFIRM_TAG) and isEnabled())
        compose.onNodeWithTag(CONNECT_LINK_CONFIRM_TAG).performClick()
    }

    /**
     * No task of the app keeps the link (and its key) in its intent, e.g. for Recents. The
     * link's own task is removed once ConnectLinkActivity finishes, which the system does
     * asynchronously, hence the wait.
     */
    private fun assertNoLinkInTasks() {
        val activities = context.getSystemService(ActivityManager::class.java)
        compose.waitUntil(TIMEOUT_MS) {
            activities.appTasks.none { it.taskInfo?.baseIntent?.data != null }
        }
        instrumentation.runOnMainSync {
            ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED)
                .forEach { assertNull(it.intent.data) }
        }
    }

    @Test
    fun confirmingTheLinkConnectsAndOpensListenNow() {
        launchWithLink()
        waitFor(hasText(text(R.string.connect_link_title, HOST)))
        waitFor(hasText("$SERVER/"))
        assertNoLinkInTasks()

        confirm()

        waitFor(hasTestTag(TITLE_TAG) and hasText(text(R.string.tab_listen_now)))
        waitForNo(hasTestTag(CONNECT_LINK_DIALOG_TAG))
        assertEquals(FakeTunesApi.config, configSource.config.value)
    }

    @Test
    fun aLinkStartedInsideAnotherTaskShowsInTheVisibleApp() {
        scenario = ActivityScenario.launch(MainActivity::class.java)
        waitFor(hasTestTag(CONNECT_SERVER_URL_TAG))

        // Without FLAG_ACTIVITY_NEW_TASK, as a camera app may do from its own activity.
        scenario?.onActivity { it.startActivity(linkIntent(connectLink())) }

        waitFor(hasText(text(R.string.connect_link_title, HOST)))
        assertNoLinkInTasks()
        confirm()
        waitFor(hasTestTag(TITLE_TAG) and hasText(text(R.string.tab_listen_now)))
        assertEquals(FakeTunesApi.config, configSource.config.value)
    }

    @Test
    fun cancellingTheLinkStaysOnConnect() {
        launchWithLink()
        waitFor(hasTestTag(CONNECT_LINK_DIALOG_TAG))

        compose.onNodeWithTag(CONNECT_LINK_CANCEL_TAG).performClick()

        waitForNo(hasTestTag(CONNECT_LINK_DIALOG_TAG))
        waitFor(hasTestTag(CONNECT_SERVER_URL_TAG))
        assertNull(configSource.config.value)
    }

    @Test
    fun aSecondLinkDoesNotReplaceTheDialog() {
        launchWithLink()
        waitFor(hasText(text(R.string.connect_link_title, HOST)))

        launchWithLink(
            "ultimatetunes://connect?url=${encode("https://evil.example.net")}&key=${
                encode(FakeTunesApi.API_KEY)
            }"
        )

        waitFor(hasText(text(R.string.connect_link_busy)))
        waitFor(hasText(text(R.string.connect_link_title, HOST)))
        compose.onNodeWithTag(CONNECT_LINK_CANCEL_TAG).performClick()
        waitForNo(hasTestTag(CONNECT_LINK_DIALOG_TAG))
        assertNull(configSource.config.value)
    }

    @Test
    fun aRefusedKeyWhileConnectedKeepsTheCurrentServer() {
        val current = ServerConfig(
            "https://old.example.net/".toHttpUrl(),
            ApiKeySecret(FakeTunesApi.API_KEY)
        )
        configSource.set(current)
        // Well-formed, but not the fake server's key; built at run time.
        launchWithLink(connectLink(key = "utk_" + "Q".repeat(43)))
        waitFor(hasText(text(R.string.connect_link_replaces)))

        confirm()

        waitFor(hasText(text(R.string.connect_error_key_refused)))
        compose.onNodeWithTag(CONNECT_LINK_CANCEL_TAG).performClick()
        waitForNo(hasTestTag(CONNECT_LINK_DIALOG_TAG))
        assertEquals(current, configSource.config.value)
    }

    @Test
    fun aMalformedLinkIsRefusedWithAClearMessage() {
        launchWithLink("ultimatetunes://connect?url=x")

        waitFor(hasText(text(R.string.connect_link_error_malformed)))
        compose.onNodeWithTag(CONNECT_LINK_CANCEL_TAG).performClick()
        waitForNo(hasTestTag(CONNECT_LINK_DIALOG_TAG))
        assertNull(configSource.config.value)
    }

    private companion object {
        const val HOST = "music.example.net"
        const val SERVER = "https://$HOST"
        const val TIMEOUT_MS = 10_000L
    }
}
