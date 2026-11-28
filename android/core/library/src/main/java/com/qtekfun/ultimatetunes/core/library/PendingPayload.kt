// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.library.db.PendingChangeEntity
import com.qtekfun.ultimatetunes.core.library.pending.ChangeKind
import com.qtekfun.ultimatetunes.core.library.pending.PlaylistEdit
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** What a row of the queue holds besides its kind and target; each kind uses a few fields. */
@Serializable
internal data class PendingPayload(
    /** The playlist's name (the new one of a create or a rename; for notices otherwise). */
    val name: String? = null,
    /** Songs the catalog may not have, to show them until a sync brings them. */
    val songs: List<Song> = emptyList(),
    /** The ids to add, or the new order. */
    val ids: List<String> = emptyList(),
    val atLeast: Map<String, Int> = emptyMap(),
    val removed: String? = null,
    val occurrence: Int = 0,
    val atMost: Int = 0,
    /** Starred or unstarred; for a notice, whether the playlist is gone from the server. */
    val flag: Boolean = false,
    /** When it was played or starred, in epoch milliseconds. */
    val at: Long = 0,
    /** The request that must not be repeated blindly (a create, a play) was already made. */
    val tried: Boolean = false,
    /** Playlists of the same name the server had before a create was tried. */
    val existing: List<String> = emptyList()
) {
    fun encode(): String = FORMAT.encodeToString(serializer(), this)

    companion object {
        private val FORMAT = Json { ignoreUnknownKeys = true }

        /** An empty payload when [text] cannot be read. */
        fun decode(text: String): PendingPayload = try {
            FORMAT.decodeFromString(serializer(), text)
        } catch (_: IllegalArgumentException) {
            PendingPayload()
        }
    }
}

internal fun PendingChangeEntity.data(): PendingPayload = PendingPayload.decode(payload)

/** The edit of the songs of a playlist this row holds, if it holds one. */
internal fun PendingChangeEntity.edit(): PlaylistEdit? {
    val data = data()
    return when (ChangeKind.of(kind)) {
        ChangeKind.ADD -> PlaylistEdit.Add(data.ids, data.atLeast)

        ChangeKind.REMOVE -> data.removed?.let {
            PlaylistEdit.Remove(it, data.occurrence, data.atMost)
        }

        ChangeKind.REORDER -> PlaylistEdit.Reorder(data.ids)

        else -> null
    }
}
