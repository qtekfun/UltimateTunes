// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library.pending

import com.qtekfun.ultimatetunes.core.api.ErrorKind
import com.qtekfun.ultimatetunes.core.api.TunesResult

/** What a queued row is. Rows of a [family] on the same target are sent together. */
internal enum class ChangeKind(val family: Family) {
    CREATE(Family.PLAYLIST),
    RENAME(Family.PLAYLIST),
    DELETE(Family.PLAYLIST),
    ADD(Family.PLAYLIST),
    REMOVE(Family.PLAYLIST),
    REORDER(Family.PLAYLIST),
    FAVOURITE_SONG(Family.SONG_FAVOURITE),
    FAVOURITE_ALBUM(Family.ALBUM_FAVOURITE),
    SCROBBLE(Family.SCROBBLE),

    /** Not to be sent: what the user has to be told. */
    NOTICE(Family.NOT_SENT),

    /** Not to be sent: the server id of a playlist made on the phone. */
    ALIAS(Family.NOT_SENT);

    enum class Family { PLAYLIST, SONG_FAVOURITE, ALBUM_FAVOURITE, SCROBBLE, NOT_SENT }

    companion object {
        fun of(name: String): ChangeKind? = entries.firstOrNull { it.name == name }
    }
}

/** A row of the queue, as much as the order of sending needs. */
internal interface Queued {
    val seq: Long
    val kind: String
    val targetId: String?
}

/**
 * The rows to send next: the oldest one not in [skipped] and, with it, every other row of the same
 * thing (all the changes of one playlist, all the stars and unstars of one song). A play is sent
 * on its own. Empty when there is nothing left to try.
 */
internal fun <T : Queued> nextGroup(rows: List<T>, skipped: Set<Long>): List<T> {
    fun familyOf(row: T) = ChangeKind.of(row.kind)?.family
    val first = rows.firstOrNull {
        it.seq !in skipped && familyOf(it).let { f -> f != null && f != ChangeKind.Family.NOT_SENT }
    } ?: return emptyList()
    val family = familyOf(first)
    return if (family == ChangeKind.Family.SCROBBLE) {
        listOf(first)
    } else {
        rows.filter { familyOf(it) == family && it.targetId == first.targetId }
    }
}

/** What the rows of one playlist amount to. */
internal enum class PlaylistPlan {
    /** Made and deleted on the phone before the server ever heard of it. */
    FORGET,

    /** Deleted, but a create may have reached the server: delete it only if it is there. */
    DELETE_IF_CREATED,
    DELETE,

    /** Make it (or find the one a lost answer left), then bring it up to date. */
    CREATE_AND_UPDATE,
    UPDATE
}

internal fun planOf(created: Boolean, createTried: Boolean, deleted: Boolean): PlaylistPlan = when {
    created && deleted && !createTried -> PlaylistPlan.FORGET
    created && deleted -> PlaylistPlan.DELETE_IF_CREATED
    created -> PlaylistPlan.CREATE_AND_UPDATE
    deleted -> PlaylistPlan.DELETE
    else -> PlaylistPlan.UPDATE
}

/** What a failed request does to the queue. */
internal enum class FailureEffect {
    /** Nothing can be sent now: keep everything and stop. */
    STOP,

    /** Keep these rows for another time and go on with the rest. */
    LATER,

    /** The server will never take it: drop it and tell the user. */
    DROP
}

private val REFUSALS = setOf(
    ErrorKind.MISSING_PARAMETER,
    ErrorKind.INVALID_PARAMETER,
    ErrorKind.INVALID_ID,
    ErrorKind.FORBIDDEN,
    ErrorKind.NOT_FOUND,
    ErrorKind.CONFLICT,
    ErrorKind.PAYLOAD_TOO_LARGE,
    ErrorKind.FEATURE_DISABLED,
    ErrorKind.UNSUPPORTED_URL,
    ErrorKind.NOT_IMPLEMENTED
)

internal fun effectOf(failure: TunesResult.Failure): FailureEffect = when (failure) {
    is TunesResult.NetworkError,
    is TunesResult.Unauthorized,
    TunesResult.NotConfigured -> FailureEffect.STOP

    is TunesResult.ProtocolError -> FailureEffect.LATER

    is TunesResult.ApiError ->
        if (failure.error.kind in REFUSALS) FailureEffect.DROP else FailureEffect.LATER
}

internal fun TunesResult.Failure.isNotFound(): Boolean =
    this is TunesResult.ApiError && error.kind == ErrorKind.NOT_FOUND
