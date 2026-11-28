// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library.pending

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class PlaylistEditTest {
    private fun list(text: String) = text.map { it.toString() }

    /** [edit] over [songs] gives [expected], and applying it again changes nothing. */
    private fun check(edit: PlaylistEdit, songs: String, expected: String) {
        val once = edit.applyTo(list(songs))
        assertEquals(list(expected), once)
        assertEquals(once, edit.applyTo(once))
    }

    @Test
    fun `adding appends to whatever the playlist holds now`() {
        val add = PlaylistEdit.add(list("ab"), list("cd"))

        check(add, "ab", "abcd")
        check(add, "abx", "abxcd")
        check(add, "abc", "abcd")
    }

    @Test
    fun `adding a song already held makes a second copy only once`() {
        val add = PlaylistEdit.add(list("a"), list("a"))

        check(add, "a", "aa")
        check(add, "aa", "aa")
        check(add, "", "aa")
    }

    @Test
    fun `an addition whose counts are unknown wants one copy`() {
        check(PlaylistEdit.Add(list("z"), emptyMap()), "a", "az")
    }

    @Test
    fun `refused songs are left out of additions and nothing else`() {
        val refused = setOf("b")

        assertEquals(
            PlaylistEdit.Add(list("c"), mapOf("c" to 1)),
            PlaylistEdit.Add(list("bc"), mapOf("b" to 1, "c" to 1)).leavingOut(refused)
        )
        val reorder = PlaylistEdit.Reorder(list("ab"))
        assertEquals(reorder, reorder.leavingOut(refused))
    }

    @Test
    fun `removing takes the song wherever it is now`() {
        val remove = PlaylistEdit.remove(list("abc"), list("abc"), 1)

        check(remove, "abc", "ac")
        check(remove, "xxcab", "xxca")
        check(remove, "ac", "ac")
    }

    @Test
    fun `removing a repeated song takes the copy picked`() {
        check(PlaylistEdit.remove(list("abaca"), list("abaca"), 2), "abaca", "abca")
        check(PlaylistEdit.remove(list("aba"), list("aba"), 2), "xa", "xa")
        check(PlaylistEdit.Remove("a", 1, 0), "abaca", "bc")
        // The catalog had no copy left to count: none may stay.
        check(PlaylistEdit.remove(emptyList(), list("a"), 0), "a", "")
    }

    @Test
    fun `reordering keeps songs added elsewhere and does not bring removed ones back`() {
        val reorder = PlaylistEdit.Reorder(list("cba"))

        check(reorder, "abc", "cba")
        check(reorder, "abxcy", "cbaxy")
        check(reorder, "ac", "ca")
        check(PlaylistEdit.Reorder(list("aba")), "aaab", "abaa")
    }

    @Test
    fun `a song archived since goes by its new id`() {
        val alias: (String) -> String = { if (it == "a") "z" else it }

        assertEquals(
            PlaylistEdit.Add(list("zb"), mapOf("z" to 1, "b" to 2)),
            PlaylistEdit.Add(list("ab"), mapOf("a" to 1, "b" to 2)).renamed(alias)
        )
        assertEquals(PlaylistEdit.Remove("z", 0, 1), PlaylistEdit.Remove("a", 0, 1).renamed(alias))
        assertEquals(
            PlaylistEdit.Reorder(list("bz")),
            PlaylistEdit.Reorder(list("ba")).renamed(alias)
        )
    }
}
