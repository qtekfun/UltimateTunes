// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.youtube

import com.qtekfun.ultimatetunes.core.api.cookies.NetscapeCookies
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.closeForTest
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.dropConnection
import com.qtekfun.ultimatetunes.ui.jsonResponse
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.problem
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

/** A cookie jar in memory (invented cookies only). */
private class FakeWebSession(var youtube: String? = null) : YoutubeWebSession {
    var clears = 0

    override fun cookieSources() = listOf(
        NetscapeCookies.Source(youtube, ".youtube.com", "www.youtube.com"),
        NetscapeCookies.Source(youtube, ".youtube.com", "music.youtube.com"),
        NetscapeCookies.Source("SID=g1", ".google.com", "accounts.google.com")
    )

    override fun clear() {
        clears++
        youtube = null
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
@ExtendWith(MainDispatcherExtension::class)
class YoutubeAccountViewModelTest {
    private val clock = Clock.fixed(Instant.parse("2026-10-13T00:00:00Z"), ZoneOffset.UTC)
    private val signedIn = "SID=a; SAPISID=b; LOGIN_INFO=c"
    private lateinit var server: FakeTunesServer
    private val session = FakeWebSession()
    private val created = mutableListOf<YoutubeAccountViewModel>()

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        created.forEach { it.closeForTest() }
        server.close()
    }

    private fun viewModel() =
        YoutubeAccountViewModel(connectedApi(server), session, clock).also { created += it }

    private suspend fun YoutubeAccountViewModel.loaded(): YoutubeAccountUiState =
        state.awaitFirst { it.status !is YoutubeStatus.Loading }

    private suspend fun YoutubeAccountViewModel.reach(phase: YoutubePhase) =
        state.awaitFirst { it.phase == phase }

    private fun requests() = List(server.requestCount) { server.takeRequest() }

    private fun putBody(): String? = requests().firstOrNull { it.method == "PUT" }?.body?.utf8()

    @Test
    fun `the status comes from the server`() = runTest {
        val state = viewModel().loaded()

        val ready = state.status as YoutubeStatus.Ready
        assertTrue(ready.value.configured)
        assertEquals(12, ready.value.cookieCount)
        assertEquals(YoutubePhase.IDLE, state.phase)
    }

    @Test
    fun `a non-admin key hides the controls`() = runTest {
        server.dispatcher.override("ut/v1/youtube-cookies/status") { problem(403, "forbidden") }
        val viewModel = viewModel()

        assertEquals(YoutubeStatus.NotAdmin, viewModel.loaded().status)
        viewModel.startSignIn()
        assertEquals(YoutubePhase.IDLE, viewModel.state.value.phase)
    }

    @Test
    fun `a failed status can be retried`() = runTest {
        server.dispatcher.override("ut/v1/youtube-cookies/status") { dropConnection() }
        val viewModel = viewModel()
        assertEquals(YoutubeStatus.Failed(LoadError.NETWORK), viewModel.loaded().status)

        server.dispatcher.clearOverrides()
        viewModel.load()

        assertTrue(
            viewModel.state.awaitFirst {
                it.status is YoutubeStatus.Ready
            }.status is YoutubeStatus.Ready
        )
    }

    @Test
    fun `warning, sign in, upload, done`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()

        viewModel.startSignIn()
        assertEquals(YoutubePhase.WARNING, viewModel.state.value.phase)
        assertEquals(0, session.clears)
        viewModel.confirmWarning()
        assertEquals(YoutubePhase.SIGNING_IN, viewModel.state.value.phase)
        assertEquals(1, session.clears) // a clean jar before the login

        session.youtube = signedIn
        viewModel.onPageFinished("www.youtube.com")
        val done = viewModel.reach(YoutubePhase.DONE)

        assertEquals(2, session.clears) // wiped right after reading
        assertEquals(null, session.youtube)
        assertEquals(null, done.failure)
        val body = checkNotNull(putBody())
        assertTrue(body.startsWith(NetscapeCookies.HEADER + "\n"))
        assertTrue(body.contains(".youtube.com\tTRUE\t/\tTRUE\t1823385600\tSAPISID\tb\n"))
        assertTrue(body.contains(".google.com\tTRUE\t/\tTRUE\t1823385600\tSID\tg1\n"))
        assertEquals(2, ((done.status as YoutubeStatus.Ready).value.cookieCount))
        viewModel.cancel()
        assertEquals(YoutubePhase.IDLE, viewModel.state.value.phase)
    }

    @Test
    fun `pages before the sign in completes do nothing`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()
        viewModel.onPageFinished("www.youtube.com") // not signing in yet
        viewModel.startSignIn()
        viewModel.confirmWarning()

        viewModel.onPageFinished("accounts.google.com") // login page
        viewModel.onPageFinished(null)
        session.youtube = "VISITOR_INFO1_LIVE=x; YSC=y" // anonymous visit
        viewModel.onPageFinished("www.youtube.com")

        assertEquals(YoutubePhase.SIGNING_IN, viewModel.state.value.phase)
        assertTrue(requests().none { it.method == "PUT" })
    }

    @Test
    fun `cancelling the warning or the login leaves nothing`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()
        viewModel.startSignIn()
        viewModel.cancel()
        assertEquals(YoutubePhase.IDLE, viewModel.state.value.phase)
        assertEquals(0, session.clears)

        viewModel.startSignIn()
        viewModel.confirmWarning()
        session.youtube = signedIn
        viewModel.cancel()

        assertEquals(YoutubePhase.IDLE, viewModel.state.value.phase)
        assertEquals(null, session.youtube)
        viewModel.confirmWarning() // no warning shown: ignored
        assertEquals(YoutubePhase.IDLE, viewModel.state.value.phase)
    }

    @Test
    fun `destroying the screen mid login wipes the jar`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()
        viewModel.startSignIn()
        viewModel.confirmWarning()
        val before = session.clears
        session.youtube = signedIn

        viewModel.onCleared()

        assertEquals(before + 1, session.clears)
        assertEquals(null, session.youtube)
    }

    @Test
    fun `clearing an idle screen touches nothing, a released WebView always wipes`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()
        viewModel.onCleared()
        assertEquals(0, session.clears)

        viewModel.webViewReleased()
        assertEquals(1, session.clears)
    }

    @Test
    fun `an anonymous jar is not even serialized`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()
        viewModel.startSignIn()
        viewModel.confirmWarning()
        session.youtube = "YSC=y"

        viewModel.onPageFinished("www.youtube.com")

        assertEquals(YoutubePhase.SIGNING_IN, viewModel.state.value.phase)
    }

    @Test
    fun `continue now captures a session that no page event saw`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()
        viewModel.startSignIn()
        viewModel.confirmWarning()
        session.youtube = signedIn

        viewModel.continueNow()

        assertEquals(YoutubePhase.DONE, viewModel.reach(YoutubePhase.DONE).phase)
        assertEquals(null, session.youtube)
    }

    @Test
    fun `continue now without a session says so and stays on the login`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()
        viewModel.continueNow() // not signing in: ignored
        viewModel.startSignIn()
        viewModel.confirmWarning()
        session.youtube = "YSC=y"

        viewModel.continueNow()

        val state = viewModel.state.value
        assertEquals(YoutubePhase.SIGNING_IN, state.phase)
        assertTrue(state.noSession)
        viewModel.onPageFinished("accounts.google.com")
        session.youtube = signedIn
        viewModel.continueNow()
        assertFalse(viewModel.reach(YoutubePhase.DONE).noSession)
    }

    @Test
    fun `a page that cannot load is reported, and clears with the next page`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()
        viewModel.onLoadFailed() // not signing in: ignored
        viewModel.startSignIn()
        viewModel.confirmWarning()

        viewModel.onLoadFailed()
        assertTrue(viewModel.state.value.loadFailed)
        viewModel.onPageFinished("accounts.google.com")

        assertFalse(viewModel.state.value.loadFailed)
        viewModel.cancel()
        assertFalse(viewModel.state.value.noSession)
    }

    @Test
    fun `the jar is polled while the login is open, whatever the page does`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()
        viewModel.startSignIn()
        viewModel.confirmWarning()

        testScheduler.advanceTimeBy(3_500) // no session yet, no page event at all
        assertEquals(YoutubePhase.SIGNING_IN, viewModel.state.value.phase)
        session.youtube = signedIn
        testScheduler.advanceTimeBy(1_500)

        assertEquals(YoutubePhase.DONE, viewModel.reach(YoutubePhase.DONE).phase)
        assertEquals(null, session.youtube)
    }

    @Test
    fun `cancelling stops the polling`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()
        viewModel.startSignIn()
        viewModel.confirmWarning()
        viewModel.cancel()
        session.youtube = signedIn

        testScheduler.advanceTimeBy(20_000)

        assertEquals(YoutubePhase.IDLE, viewModel.state.value.phase)
    }

    @Test
    fun `a server without a cookie key refuses to start`() = runTest {
        server.dispatcher.override("ut/v1/youtube-cookies/status") {
            jsonResponse("""{"configured":false,"available":false}""")
        }
        val viewModel = viewModel()
        viewModel.loaded()

        viewModel.startSignIn()

        assertEquals(YoutubePhase.IDLE, viewModel.state.value.phase)
    }

    private suspend fun failUpload(
        viewModel: YoutubeAccountViewModel,
        response: () -> mockwebserver3.MockResponse
    ): YoutubeAccountUiState {
        server.dispatcher.override("ut/v1/youtube-cookies") { response() }
        viewModel.loaded()
        viewModel.startSignIn()
        viewModel.confirmWarning()
        session.youtube = signedIn
        viewModel.onPageFinished("m.youtube.com")
        return viewModel.reach(YoutubePhase.FAILED)
    }

    @Test
    fun `upload failures are told apart`() = runTest {
        val cases = listOf(
            { problem(403, "forbidden") } to YoutubeFailure.NOT_ADMIN,
            { problem(409, "feature_disabled") } to YoutubeFailure.FEATURE_DISABLED,
            { problem(400, "invalid_parameter") } to YoutubeFailure.REJECTED,
            { problem(413, "payload_too_large") } to YoutubeFailure.TOO_LARGE,
            { problem(429, "rate_limited") } to YoutubeFailure.RATE_LIMITED,
            { problem(401, "invalid_api_key") } to YoutubeFailure.UNAUTHORIZED,
            { problem(500, "internal_error") } to YoutubeFailure.SERVER,
            { jsonResponse("[]") } to YoutubeFailure.SERVER,
            { dropConnection() } to YoutubeFailure.NETWORK
        )
        for ((response, expected) in cases) {
            val viewModel = viewModel()
            val failed = failUpload(viewModel, response)
            assertEquals(expected, failed.failure, "for $expected")
            assertEquals(null, session.youtube)
            viewModel.cancel()
            assertEquals(null, viewModel.state.value.failure)
        }
    }

    @Test
    fun `sign out clears the server session`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()

        viewModel.remove()

        val state = viewModel.state.awaitFirst {
            (it.status as? YoutubeStatus.Ready)?.value?.configured == false
        }
        assertEquals(YoutubePhase.IDLE, state.phase)
        assertTrue(requests().any { it.method == "DELETE" })
    }

    @Test
    fun `sign out failing shows why`() = runTest {
        server.dispatcher.override("ut/v1/youtube-cookies") { problem(403, "forbidden") }
        val viewModel = viewModel()
        viewModel.loaded()

        viewModel.remove()

        assertEquals(YoutubeFailure.NOT_ADMIN, viewModel.reach(YoutubePhase.FAILED).failure)
    }

    @Test
    fun `nothing starts while busy or before the status is known`() = runTest {
        val viewModel = viewModel()
        viewModel.remove() // status still loading
        viewModel.startSignIn()
        assertEquals(YoutubePhase.IDLE, viewModel.state.value.phase)
        viewModel.loaded()
        viewModel.startSignIn()
        viewModel.startSignIn() // already in the warning
        viewModel.remove() // busy
        assertEquals(YoutubePhase.WARNING, viewModel.state.value.phase)
    }

    @Test
    fun `the state never holds cookie text`() = runTest {
        val viewModel = viewModel()
        viewModel.loaded()
        viewModel.startSignIn()
        viewModel.confirmWarning()
        session.youtube = "SID=topsecret; SAPISID=topsecret2"
        viewModel.onPageFinished("www.youtube.com")

        val done = viewModel.reach(YoutubePhase.DONE)

        assertFalse(done.toString().contains("topsecret"))
    }
}
