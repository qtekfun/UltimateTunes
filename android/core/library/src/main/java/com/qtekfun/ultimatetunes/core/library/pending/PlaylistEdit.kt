// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library.pending

/**
 * What the user meant to do to the songs of a playlist, by song id and never by position, so it
 * can be applied over whatever the playlist holds later. Applying an edit (or a whole sequence of
 * them) a second time changes nothing, so a write whose answer was lost can be repeated.
 */
internal sealed interface PlaylistEdit {
    fun applyTo(songs: List<String>): List<String>

    /** The same edit with every id passed through [alias] (a `yt:` song now in the library). */
    fun renamed(alias: (String) -> String): PlaylistEdit

    /** Append [ids] until the playlist holds each one [atLeast] times. */
    data class Add(val ids: List<String>, val atLeast: Map<String, Int>) : PlaylistEdit {
        override fun applyTo(songs: List<String>): List<String> {
            val result = songs.toMutableList()
            val held = HashMap<String, Int>()
            songs.forEach { held[it] = (held[it] ?: 0) + 1 }
            fun addIfShort(id: String): Boolean {
                val count = held[id] ?: 0
                val short = count < (atLeast[id] ?: 1)
                if (short) {
                    result += id
                    held[id] = count + 1
                }
                return short
            }
            ids.forEach(::addIfShort)
            // Copies it had before and lost elsewhere: all at once, so a repeat adds nothing.
            ids.distinct().forEach {
                while (addIfShort(it)) continue
            }
            return result
        }

        override fun renamed(alias: (String) -> String) = Add(
            ids.map(alias),
            atLeast.mapKeys { alias(it.key) }
        )
    }

    /**
     * Take copies of [id] away while there are more than [atMost]; the one the user picked was the
     * [occurrence]-th (from 0).
     */
    data class Remove(val id: String, val occurrence: Int, val atMost: Int) : PlaylistEdit {
        override fun applyTo(songs: List<String>): List<String> {
            val result = songs.toMutableList()
            val places = result.indices.filter { result[it] == id }.toMutableList()
            while (places.size > atMost) {
                val place = places.removeAt(minOf(occurrence, places.lastIndex))
                result.removeAt(place)
                // The later copies moved one up.
                places.indices.forEach { if (places[it] > place) places[it]-- }
            }
            return result
        }

        override fun renamed(alias: (String) -> String) = copy(id = alias(id))
    }

    /**
     * Put the songs in [order]. A song that is gone is not brought back; one that [order] does not
     * know (added elsewhere) goes after, in the order it had.
     */
    data class Reorder(val order: List<String>) : PlaylistEdit {
        override fun applyTo(songs: List<String>): List<String> {
            val left = HashMap<String, Int>()
            songs.forEach { left[it] = (left[it] ?: 0) + 1 }
            val result = ArrayList<String>(songs.size)
            for (id in order) {
                val count = left[id] ?: 0
                if (count > 0) {
                    result += id
                    left[id] = count - 1
                }
            }
            val placed = HashMap<String, Int>()
            result.forEach { placed[it] = (placed[it] ?: 0) + 1 }
            for (id in songs) {
                val skip = placed[id] ?: 0
                if (skip > 0) placed[id] = skip - 1 else result += id
            }
            return result
        }

        override fun renamed(alias: (String) -> String) = Reorder(order.map(alias))
    }

    companion object {
        /** Adding [ids] to a playlist that holds [current]. */
        fun add(current: List<String>, ids: List<String>): Add {
            val wanted = current + ids
            return Add(ids, ids.associateWith { id -> wanted.count { it == id } })
        }

        /** Removing the song [shown] has at [index] from a playlist that holds [current]. */
        fun remove(current: List<String>, shown: List<String>, index: Int): Remove {
            val id = shown[index]
            return Remove(
                id = id,
                occurrence = shown.subList(0, index).count { it == id },
                atMost = maxOf(current.count { it == id } - 1, 0)
            )
        }
    }
}
