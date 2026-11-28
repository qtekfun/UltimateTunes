// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.search

import com.qtekfun.ultimatetunes.ui.fakeRecentSearches
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class RecentSearchesTest {
    private val store = fakeRecentSearches()

    private suspend fun stored() = store.searches.first()

    @Test
    fun `newest first, without repeats whatever the case, and blanks ignored`() = runTest {
        store.add("lanterns")
        store.add("harbour\nlights")
        store.add("   ")
        store.add(" Lanterns ")

        assertEquals(listOf("Lanterns", "harbour lights"), stored())
    }

    @Test
    fun `only the last ones are kept`() = runTest {
        repeat(DataStoreRecentSearches.MAX_SEARCHES + 2) { store.add("q$it") }

        assertEquals(DataStoreRecentSearches.MAX_SEARCHES, stored().size)
        assertEquals("q11", stored().first())
        assertEquals("q2", stored().last())
    }

    @Test
    fun `removing and clearing`() = runTest {
        store.add("a")
        store.add("b")

        store.remove("a")
        assertEquals(listOf("b"), stored())

        store.clear()
        assertEquals(emptyList<String>(), stored())
    }

    @Test
    fun `only another server forgets them`() = runTest {
        store.serverConnected("https://one.example/")
        store.add("a")

        store.serverConnected("https://one.example/")
        assertEquals(listOf("a"), stored())

        store.serverConnected("https://two.example/")
        assertEquals(emptyList<String>(), stored())
    }
}
