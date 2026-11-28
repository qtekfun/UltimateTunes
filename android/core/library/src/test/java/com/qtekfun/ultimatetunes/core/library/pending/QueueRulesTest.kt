// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library.pending

import com.qtekfun.ultimatetunes.core.api.ErrorKind
import com.qtekfun.ultimatetunes.core.api.TunesError
import com.qtekfun.ultimatetunes.core.api.TunesResult
import java.io.IOException
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class QueueRulesTest {
    private data class Row(
        override val seq: Long,
        override val kind: String,
        override val targetId: String?
    ) : Queued

    private fun error(kind: ErrorKind) = TunesResult.ApiError(TunesError(kind), 200)

    @Test
    fun `all the changes of the oldest playlist go together`() {
        val rows = listOf(
            Row(1, "NOTICE", "a"),
            Row(2, "unknown", "a"),
            Row(3, "ADD", "a"),
            Row(4, "ADD", "b"),
            Row(5, "FAVOURITE_SONG", "a"),
            Row(6, "DELETE", "a")
        )

        assertEquals(listOf(3L, 6L), nextGroup(rows, emptySet()).map { it.seq })
        assertEquals(listOf(4L), nextGroup(rows, setOf(3L, 6L)).map { it.seq })
        assertEquals(listOf(5L), nextGroup(rows, setOf(3L, 4L, 6L)).map { it.seq })
        assertTrue(nextGroup(rows, setOf(3L, 4L, 5L, 6L)).isEmpty())
    }

    @Test
    fun `each play goes on its own`() {
        val rows = listOf(Row(1, "SCROBBLE", "a"), Row(2, "SCROBBLE", "a"))

        assertEquals(listOf(1L), nextGroup(rows, emptySet()).map { it.seq })
    }

    @Test
    fun `notices and ids are never sent`() {
        val rows = listOf(Row(1, "NOTICE", "a"), Row(2, "ALIAS", "a"))

        assertTrue(nextGroup(rows, emptySet()).isEmpty())
    }

    @Test
    fun `what the changes of a playlist amount to`() {
        assertEquals(PlaylistPlan.UPDATE, planOf(false, false, false))
        assertEquals(PlaylistPlan.DELETE, planOf(false, false, true))
        assertEquals(PlaylistPlan.CREATE_AND_UPDATE, planOf(true, false, false))
        assertEquals(PlaylistPlan.CREATE_AND_UPDATE, planOf(true, true, false))
        assertEquals(PlaylistPlan.FORGET, planOf(true, false, true))
        assertEquals(PlaylistPlan.DELETE_IF_CREATED, planOf(true, true, true))
    }

    @Test
    fun `failures stop, wait or drop`() {
        assertEquals(FailureEffect.STOP, effectOf(TunesResult.NetworkError(IOException())))
        assertEquals(FailureEffect.STOP, effectOf(TunesResult.NotConfigured))
        assertEquals(
            FailureEffect.STOP,
            effectOf(TunesResult.Unauthorized(TunesError(ErrorKind.INVALID_API_KEY), 401))
        )
        assertEquals(FailureEffect.LATER, effectOf(TunesResult.ProtocolError("html", 502)))
        listOf(ErrorKind.RATE_LIMITED, ErrorKind.INTERNAL, ErrorKind.UPSTREAM_UNAVAILABLE)
            .forEach { assertEquals(FailureEffect.LATER, effectOf(error(it)), it.name) }
        listOf(ErrorKind.NOT_FOUND, ErrorKind.FORBIDDEN, ErrorKind.PAYLOAD_TOO_LARGE)
            .forEach { assertEquals(FailureEffect.DROP, effectOf(error(it)), it.name) }
    }

    @Test
    fun `only a not found answer says something is gone`() {
        assertTrue(error(ErrorKind.NOT_FOUND).isNotFound())
        assertFalse(error(ErrorKind.FORBIDDEN).isNotFound())
        assertFalse(TunesResult.NotConfigured.isNotFound())
    }

    @Test
    fun `kinds are read by name`() {
        assertEquals(ChangeKind.ADD, ChangeKind.of("ADD"))
        assertEquals(null, ChangeKind.of("add"))
    }
}
