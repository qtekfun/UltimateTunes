// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library.pending

/** The most ids one write takes, and the most songs not in the library yet among them. */
internal data class WriteLimits(val ids: Int = 1_000, val newSongs: Int = 50)

/** One request that brings a playlist closer to what it should hold. */
internal sealed interface PlaylistWrite {
    /** `createPlaylist` with `playlistId`: the whole list at once. */
    data class Replace(val ids: List<String>) : PlaylistWrite

    /** `updatePlaylist`: positions taken out and songs appended, in one transaction. */
    data class Change(val removeIndexes: List<Int>, val add: List<String>) : PlaylistWrite
}

/**
 * The next request that takes a playlist from [current] to [desired], or null when it is there.
 * Whatever request fails, the playlist still holds every song that both lists have: a list short
 * enough goes whole; a longer one is changed in place, and reordered by moving songs to the end
 * with a request that removes and appends them at once.
 */
internal fun nextWrite(
    current: List<String>,
    desired: List<String>,
    limits: WriteLimits = WriteLimits()
): PlaylistWrite? {
    val held = current.toHashSet()
    val fitsWhole = desired.size <= limits.ids &&
        desired.count { it.isExternal() && it !in held } <= limits.newSongs
    return when {
        current == desired -> null
        fitsWhole -> PlaylistWrite.Replace(desired)
        else -> inPlace(current, desired, limits)
    }
}

/** For a list too long, or with too many new songs, to be written whole. */
private fun inPlace(
    current: List<String>,
    desired: List<String>,
    limits: WriteLimits
): PlaylistWrite {
    val extra = surplus(current, desired)
    val missing = surplus(desired, current).map { desired[it] }
    return when {
        extra.isNotEmpty() -> PlaylistWrite.Change(extra.take(limits.ids), emptyList())

        missing.isNotEmpty() ->
            PlaylistWrite.Change(emptyList(), chunk(missing, limits.ids, limits.newSongs))

        else -> moveToEnd(current, desired, limits)
    }
}

/** The positions of [of] holding more copies of a song than [against] has. */
private fun surplus(of: List<String>, against: List<String>): List<Int> {
    val left = HashMap<String, Int>()
    against.forEach { left[it] = (left[it] ?: 0) + 1 }
    return of.indices.filter { index ->
        val count = left[of[index]] ?: 0
        left[of[index]] = count - 1
        count <= 0
    }
}

/**
 * The same songs in another order: the start of [desired] that [current] already has in order
 * stays, and the songs after it go to the end in their turn, as many as one request takes (each
 * is both removed and added).
 */
private fun moveToEnd(
    current: List<String>,
    desired: List<String>,
    limits: WriteLimits
): PlaylistWrite {
    val staying = HashSet<Int>()
    var matched = 0
    current.forEachIndexed { index, id ->
        if (desired.getOrNull(matched) == id) {
            staying += index
            matched++
        }
    }
    val moving = chunk(desired.drop(matched), limits.ids / 2, limits.newSongs)
    val places = HashMap<String, ArrayDeque<Int>>()
    current.indices.filter { it !in staying }
        .forEach { places.getOrPut(current[it]) { ArrayDeque() }.add(it) }
    val removed = moving.map { places.getValue(it).removeFirst() }
    return PlaylistWrite.Change(removed.sorted(), moving)
}

/** The longest start of [ids] that fits in one request. */
private fun chunk(ids: List<String>, max: Int, maxNew: Int): List<String> {
    var external = 0
    return ids.asSequence()
        .take(max)
        .takeWhile { !it.isExternal() || ++external <= maxNew }
        .toList()
}

private fun String.isExternal() = startsWith("yt:")
