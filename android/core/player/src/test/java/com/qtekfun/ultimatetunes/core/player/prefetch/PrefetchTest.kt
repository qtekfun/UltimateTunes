// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.prefetch

import com.qtekfun.ultimatetunes.core.api.model.SongId
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

private val LIB_A = SongId("0190a5c8-0000-7000-8000-00000000000a")
private val LIB_B = SongId("0190a5c8-0000-7000-8000-00000000000b")
private val YT_C = SongId("yt:CCCCCCCCCCC")
private val YT_D = SongId("yt:DDDDDDDDDDD")

class PrefetchPlannerTest {
    private val planner = PrefetchPlanner(preloadBytes = 1_000)
    private val nothingCached: (SongId) -> Boolean = { false }

    @Test
    fun `the next external song is requested on the server and preloaded`() {
        val actions = planner.plan(QueueSnapshot(LIB_A, listOf(YT_C, YT_D)), nothingCached)
        assertEquals(
            listOf(PrefetchAction.RequestOnServer(YT_C), PrefetchAction.Preload(YT_C, 1_000)),
            actions
        )
    }

    @Test
    fun `a library song is only preloaded, and not when already on the phone`() {
        assertEquals(
            listOf(PrefetchAction.Preload(LIB_B, 1_000)),
            planner.plan(QueueSnapshot(LIB_A, listOf(LIB_B)), nothingCached)
        )
        assertEquals(
            listOf(PrefetchAction.RequestOnServer(YT_C)),
            planner.plan(QueueSnapshot(LIB_A, listOf(LIB_A, YT_C))) { true }
        )
    }

    @Test
    fun `each action is planned once until forgotten`() {
        val snapshot = QueueSnapshot(LIB_A, listOf(YT_C))
        val first = planner.plan(snapshot, nothingCached)
        assertEquals(2, first.size)
        assertTrue(planner.plan(snapshot, nothingCached).isEmpty())

        planner.forget(PrefetchAction.Preload(YT_C, 1_000))
        assertEquals(
            listOf(PrefetchAction.Preload(YT_C, 1_000)),
            planner.plan(snapshot, nothingCached)
        )

        planner.forget(PrefetchAction.RequestOnServer(YT_C))
        assertEquals(
            listOf(PrefetchAction.RequestOnServer(YT_C)),
            planner.plan(snapshot, nothingCached)
        )
    }

    @Test
    fun `offline only plans nothing, and the end of the queue neither`() {
        assertTrue(
            planner.plan(QueueSnapshot(LIB_A, listOf(YT_C), offlineOnly = true), nothingCached)
                .isEmpty()
        )
        assertTrue(planner.plan(QueueSnapshot(LIB_A, emptyList()), nothingCached).isEmpty())
        assertTrue(planner.plan(QueueSnapshot(null, emptyList()), nothingCached).isEmpty())
    }

    @Test
    fun `the current song and duplicates are skipped within the lookahead`() {
        val wide = PrefetchPlanner(lookahead = 2, preloadBytes = 10)
        val actions = wide.plan(
            QueueSnapshot(YT_C, listOf(YT_C, LIB_B, LIB_B, YT_D)),
            nothingCached
        )
        assertEquals(
            listOf(
                PrefetchAction.RequestOnServer(YT_D),
                PrefetchAction.Preload(LIB_B, 10),
                PrefetchAction.Preload(YT_D, 10)
            ),
            actions
        )
    }

    @Test
    fun `the memory is bounded, so an old song can be planned again`() {
        val small = PrefetchPlanner(preloadBytes = 10, memory = 1)
        small.plan(QueueSnapshot(null, listOf(LIB_A)), nothingCached)
        small.plan(QueueSnapshot(null, listOf(LIB_B)), nothingCached)
        assertEquals(
            listOf(PrefetchAction.Preload(LIB_A, 10)),
            small.plan(QueueSnapshot(null, listOf(LIB_A)), nothingCached)
        )
    }

    @Test
    fun `invalid settings are refused`() {
        assertThrows<IllegalArgumentException> { PrefetchPlanner(lookahead = 0, preloadBytes = 1) }
        assertThrows<IllegalArgumentException> { PrefetchPlanner(preloadBytes = 0) }
        assertThrows<IllegalArgumentException> {
            PrefetchPlanner(lookahead = 3, preloadBytes = 1, memory = 2)
        }
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class PrefetcherTest {
    private class FakeTarget : PrefetchTarget {
        val available = mutableSetOf<SongId>()
        val calls = mutableListOf<String>()
        var requestWorks = true
        var preloadWorks = true
        var preloadGate: CompletableDeferred<Unit>? = null

        override fun isAvailable(id: SongId): Boolean = id in available

        override suspend fun requestOnServer(id: SongId): Boolean {
            calls += "request $id"
            return requestWorks
        }

        override suspend fun preload(id: SongId, bytes: Long): Boolean {
            calls += "preload $id $bytes"
            preloadGate?.await()
            return preloadWorks
        }
    }

    private val target = FakeTarget()
    private val planner = PrefetchPlanner(preloadBytes = 100)

    @Test
    fun `runs the planned actions in order`() = runTest {
        val prefetcher = Prefetcher(planner, target, this)
        val planned = prefetcher.onQueueChanged(QueueSnapshot(LIB_A, listOf(YT_C)))
        advanceUntilIdle()

        assertEquals(2, planned.size)
        assertEquals(listOf("request yt:CCCCCCCCCCC", "preload yt:CCCCCCCCCCC 100"), target.calls)
        // Done once: the same snapshot plans nothing more.
        assertTrue(prefetcher.onQueueChanged(QueueSnapshot(LIB_A, listOf(YT_C))).isEmpty())
    }

    @Test
    fun `failed actions are planned again next time`() = runTest {
        target.requestWorks = false
        target.preloadWorks = false
        val prefetcher = Prefetcher(planner, target, this)
        prefetcher.onQueueChanged(QueueSnapshot(LIB_A, listOf(YT_C)))
        advanceUntilIdle()

        target.requestWorks = true
        target.preloadWorks = true
        assertEquals(2, prefetcher.onQueueChanged(QueueSnapshot(LIB_A, listOf(YT_C))).size)
        advanceUntilIdle()
        assertEquals(4, target.calls.size)
    }

    @Test
    fun `a new snapshot cancels the running work, which is planned again later`() = runTest {
        val scope = TestScope(StandardTestDispatcher(testScheduler))
        target.preloadGate = CompletableDeferred()
        val prefetcher = Prefetcher(planner, target, scope)
        prefetcher.onQueueChanged(QueueSnapshot(LIB_A, listOf(LIB_B)))
        scope.runCurrent()
        assertEquals(listOf("preload $LIB_B 100"), target.calls)

        // The queue moved on before the preload ended.
        prefetcher.onQueueChanged(QueueSnapshot(LIB_B, emptyList()))
        scope.runCurrent()

        target.preloadGate = null
        assertEquals(
            listOf(PrefetchAction.Preload(LIB_B, 100)),
            prefetcher.onQueueChanged(QueueSnapshot(LIB_A, listOf(LIB_B)))
        )
        scope.runCurrent()
        assertEquals(2, target.calls.size)
    }

    @Test
    fun `cancel stops the work and nothing to do starts nothing`() = runTest {
        val scope = TestScope(StandardTestDispatcher(testScheduler))
        target.available += LIB_B
        val prefetcher = Prefetcher(planner, target, scope)
        assertTrue(prefetcher.onQueueChanged(QueueSnapshot(LIB_A, listOf(LIB_B))).isEmpty())
        prefetcher.cancel()

        target.preloadGate = CompletableDeferred()
        prefetcher.onQueueChanged(QueueSnapshot(LIB_A, listOf(YT_D)))
        scope.runCurrent()
        prefetcher.cancel()
        scope.runCurrent()
        assertEquals(listOf("request yt:DDDDDDDDDDD", "preload yt:DDDDDDDDDDD 100"), target.calls)

        // The cancelled preload is planned again; the finished request is not.
        assertEquals(
            listOf(PrefetchAction.Preload(YT_D, 100)),
            planner.plan(QueueSnapshot(LIB_A, listOf(YT_D))) { false }
        )
    }
}
