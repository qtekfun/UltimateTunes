// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library.pending

import kotlin.random.Random
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class PlaylistWriteTest {
    private val small = WriteLimits(ids = 4, newSongs = 2)

    private fun ids(vararg names: String) = names.toList()

    /** What the server does with a write. */
    private fun apply(current: List<String>, write: PlaylistWrite): List<String> = when (write) {
        is PlaylistWrite.Replace -> write.ids

        is PlaylistWrite.Change ->
            current.filterIndexed { i, _ -> i !in write.removeIndexes } + write.add
    }

    private fun counts(songs: List<String>) = songs.groupingBy { it }.eachCount()

    /** Writes until there; every request within the limits and losing nothing wanted. */
    private fun settle(from: List<String>, to: List<String>, limits: WriteLimits) {
        var current = from
        var rounds = 0
        val kept = counts(from).mapValues { (id, n) -> minOf(n, counts(to)[id] ?: 0) }
        while (true) {
            val write = nextWrite(current, to, limits) ?: break
            val sent = when (write) {
                is PlaylistWrite.Replace -> write.ids.size
                is PlaylistWrite.Change -> write.removeIndexes.size + write.add.size
            }
            assertTrue(sent <= limits.ids, "too many ids in $write")
            val added = if (write is PlaylistWrite.Change) {
                write.add
            } else {
                (write as PlaylistWrite.Replace).ids.filter { it !in current }
            }
            assertTrue(added.count { it.startsWith("yt:") } <= limits.newSongs, "$write")
            current = apply(current, write)
            val now = counts(current)
            kept.forEach { (id, n) -> assertTrue((now[id] ?: 0) >= n, "lost $id in $write") }
            assertTrue(++rounds < 200, "does not settle: $from -> $to")
        }
        assertEquals(to, current)
    }

    @Test
    fun `nothing to write when the playlist is as wanted`() {
        assertNull(nextWrite(ids("a"), ids("a")))
    }

    @Test
    fun `a list that fits goes whole, an empty one too`() {
        assertEquals(
            PlaylistWrite.Replace(ids("b", "a")),
            nextWrite(ids("a", "b"), ids("b", "a"), small)
        )
        assertEquals(PlaylistWrite.Replace(emptyList()), nextWrite(ids("a"), emptyList(), small))
    }

    @Test
    fun `new songs past the cap are appended in parts before the whole list`() {
        val wanted = ids("yt:3", "yt:1", "yt:2")

        assertEquals(
            PlaylistWrite.Change(emptyList(), ids("yt:3", "yt:1")),
            nextWrite(emptyList(), wanted, small)
        )
        // Songs it already holds do not count.
        assertEquals(PlaylistWrite.Replace(wanted), nextWrite(wanted.sorted(), wanted, small))
        settle(emptyList(), wanted, small)
    }

    @Test
    fun `a long playlist is reordered by moving songs without ever dropping one`() {
        val long = (1..11).map { "s$it" } + (1..5).map { "yt:$it" }

        settle(long, long.reversed(), small)
        settle(long, long.drop(1) + long.first(), small)
        settle(long, long.take(3), small)
        settle(long.take(3), long, small)
    }

    @Test
    fun `any change of any list settles`() {
        val random = Random(35)
        val pool = (1..8).map { "s$it" } + (1..4).map { "yt:$it" }
        repeat(400) {
            val from = List(random.nextInt(14)) { pool.random(random) }
            val to = List(random.nextInt(14)) { pool.random(random) }
            settle(from, to, small)
            settle(from, from.shuffled(random), small)
        }
    }
}
