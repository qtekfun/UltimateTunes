// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.library.db.PendingChangeEntity
import com.qtekfun.ultimatetunes.core.library.db.QueueDao
import com.qtekfun.ultimatetunes.core.library.pending.ChangeKind
import com.qtekfun.ultimatetunes.core.library.pending.FailureEffect
import com.qtekfun.ultimatetunes.core.library.pending.PlaylistEdit
import com.qtekfun.ultimatetunes.core.library.pending.PlaylistPlan
import com.qtekfun.ultimatetunes.core.library.pending.PlaylistWrite
import com.qtekfun.ultimatetunes.core.library.pending.WriteLimits
import com.qtekfun.ultimatetunes.core.library.pending.effectOf
import com.qtekfun.ultimatetunes.core.library.pending.isNotFound
import com.qtekfun.ultimatetunes.core.library.pending.nextGroup
import com.qtekfun.ultimatetunes.core.library.pending.nextWrite
import com.qtekfun.ultimatetunes.core.library.pending.planOf
import java.time.Instant
import java.time.temporal.ChronoUnit

private class SendFailed(val failure: TunesResult.Failure) : Exception()

private class PlaylistGone : Exception()

/** The connection the queue belongs to, while it is sent. */
internal interface SendSession {
    /** Throws if the connection changed or the catalog was cleared. */
    fun check()

    /** One transaction, after [check]. */
    suspend fun write(block: suspend () -> Unit)
}

/**
 * Sends the queue to the server, oldest first: for a playlist it reads what the server holds,
 * applies the changes on top by song id and writes the result.
 */
@Suppress("TooManyFunctions") // One function per kind of change and step.
internal class PendingSender(
    private val api: TunesApi,
    private val dao: QueueDao,
    private val session: SendSession,
    private val limits: WriteLimits = WriteLimits()
) {
    private val local = LocalApply(dao)
    private var changed = false

    suspend fun run(): SendResult {
        val skipped = HashSet<Long>()
        while (true) {
            session.check()
            val group = nextGroup(dao.all(), skipped)
            if (group.isEmpty() || !sendOrKeep(group, skipped)) break
        }
        return SendResult(changed, waiting = nextGroup(dao.all(), emptySet()).any())
    }

    /** False when nothing else can be sent now. */
    private suspend fun sendOrKeep(
        group: List<PendingChangeEntity>,
        skipped: MutableSet<Long>
    ): Boolean = try {
        send(group)
        true
    } catch (_: PlaylistGone) {
        drop(group, deletedOnServer = true)
        true
    } catch (e: SendFailed) {
        when (effectOf(e.failure)) {
            FailureEffect.STOP -> false

            FailureEffect.LATER -> {
                skipped += group.map { it.seq }
                true
            }

            FailureEffect.DROP -> {
                drop(group, deletedOnServer = false)
                true
            }
        }
    }

    private suspend fun send(group: List<PendingChangeEntity>) {
        val first = group.first()
        val target = first.targetId.orEmpty()
        when (ChangeKind.of(first.kind)?.family) {
            ChangeKind.Family.PLAYLIST -> sendPlaylist(target, group)

            ChangeKind.Family.SONG_FAVOURITE -> {
                val ids = listOf(SongId(target))
                val on = group.last().data().flag
                (if (on) api.star(songIds = ids) else api.unstar(songIds = ids)).orFail()
                done(group)
            }

            ChangeKind.Family.ALBUM_FAVOURITE -> {
                val ids = listOf(AlbumId(target))
                val on = group.last().data().flag
                (if (on) api.star(albumIds = ids) else api.unstar(albumIds = ids)).orFail()
                done(group)
            }

            else -> {
                sendPlay(first)
                session.write { dao.remove(first.seq) }
            }
        }
    }

    /** A play counts each time it is sent, so one already tried is looked for first. */
    private suspend fun sendPlay(row: PendingChangeEntity) {
        val data = row.data()
        val id = SongId(row.targetId.orEmpty())
        val at = Instant.ofEpochMilli(data.at)
        if (data.tried) {
            val played = api.song(id).orFail().played
            // The server may keep whole seconds only.
            val second = at.truncatedTo(ChronoUnit.SECONDS)
            if (played?.truncatedTo(ChronoUnit.SECONDS) == second) return
        } else {
            session.write { dao.setPayload(row.seq, data.copy(tried = true).encode()) }
        }
        api.scrobble(id, submission = true, playedAt = at).orFail()
    }

    private suspend fun sendPlaylist(target: String, group: List<PendingChangeEntity>) {
        val create = group.firstOrNull { it.kind == ChangeKind.CREATE.name }
        val plan = planOf(
            created = create != null,
            createTried = create?.data()?.tried == true,
            deleted = group.any { it.kind == ChangeKind.DELETE.name }
        )
        when (plan) {
            PlaylistPlan.FORGET -> Unit

            PlaylistPlan.DELETE_IF_CREATED ->
                create?.let { created(it.data()) }?.let { delete(it.value) }

            PlaylistPlan.DELETE -> delete(target)

            PlaylistPlan.CREATE_AND_UPDATE -> {
                val row = checkNotNull(create)
                val id = create(row).value
                replaceId(target, id, row)
                update(id, group - row)
            }

            PlaylistPlan.UPDATE -> update(target, group)
        }
        done(group)
    }

    /** The playlist a tried create left on the server, or null. */
    private suspend fun created(data: PendingPayload): PlaylistId? {
        if (!data.tried) return null
        return api.playlists().orFail().firstOrNull {
            it.name == data.name && it.readonly != true && it.id.value !in data.existing
        }?.id
    }

    /** Makes the playlist, unless an earlier try did and its answer was lost. */
    private suspend fun create(row: PendingChangeEntity): PlaylistId {
        val data = row.data()
        created(data)?.let { return it }
        if (!data.tried) {
            val same = api.playlists().orFail().filter { it.name == data.name }
            val marked = data.copy(tried = true, existing = same.map { it.id.value })
            session.write { dao.setPayload(row.seq, marked.encode()) }
        }
        return api.createPlaylist(data.name.orEmpty()).orFail().id
    }

    /** The playlist made on the phone becomes the server's [id], everywhere at once. */
    private suspend fun replaceId(old: String, id: String, create: PendingChangeEntity) {
        session.write {
            dao.remove(create.seq)
            dao.retarget(old, id)
            val playlist = dao.playlist(old)
            if (playlist != null) {
                if (dao.playlist(id) == null) {
                    val songs = dao.entryIds(old)
                    dao.insertPlaylist(playlist.copy(id = id))
                    local.setSongs(id, songs)
                }
                local.deletePlaylist(old)
            }
            dao.add(
                PendingChangeEntity(
                    kind = ChangeKind.ALIAS.name,
                    targetId = old,
                    payload = PendingPayload(removed = id).encode(),
                    createdAt = create.createdAt
                )
            )
        }
    }

    private suspend fun delete(id: String) {
        val result = api.deletePlaylist(PlaylistId(id))
        if (result is TunesResult.Failure && !result.isNotFound()) throw SendFailed(result)
    }

    private suspend fun update(id: String, rows: List<PendingChangeEntity>) {
        if (rows.isEmpty()) return
        val playlist = read(id)
        val name = rows.lastOrNull { it.kind == ChangeKind.RENAME.name }?.data()?.name
        if (name != null && name != playlist.name) {
            api.updatePlaylist(playlist.id, name = name).orFail()
        }
        val edits = rows.mapNotNull { it.edit() }
        if (edits.isNotEmpty()) writeSongs(playlist, edits)
    }

    /** Applies [edits] over what [first] holds and writes the result, reading between writes. */
    private suspend fun writeSongs(first: Playlist, edits: List<PlaylistEdit>) {
        var playlist = first
        var pending = edits
        val aliases = HashMap<String, String>()
        // Each round reads, applies and writes once; more than this means it never settles.
        repeat(MAX_WRITES) {
            val current = playlist.entry.map { it.id.value }
            pending = withLibraryIds(pending, current, aliases)
            val desired = pending.fold(current) { songs, edit -> edit.applyTo(songs) }
            val write = nextWrite(current, desired, limits)
            if (write != null) send(playlist.id, write)
            // A whole list needs no reading back.
            if (write !is PlaylistWrite.Change) return
            playlist = read(playlist.id.value)
        }
        throw SendFailed(TunesResult.ProtocolError("Playlist did not settle", 0))
    }

    private suspend fun send(id: PlaylistId, write: PlaylistWrite) {
        val result = when (write) {
            is PlaylistWrite.Replace -> api.replacePlaylist(id, write.ids.map(::SongId))

            is PlaylistWrite.Change -> api.updatePlaylist(
                id,
                songIdsToAdd = write.add.map(::SongId),
                songIndexesToRemove = write.removeIndexes
            )
        }
        result.orFail()
    }

    private suspend fun read(id: String): Playlist {
        session.check()
        val result = api.playlist(PlaylistId(id))
        if (result is TunesResult.Failure && result.isNotFound()) throw PlaylistGone()
        return result.orFail()
    }

    /**
     * A `yt:` song archived since the change was made is under its library id on the server: asks
     * for those of [edits] that [current] does not have.
     */
    private suspend fun withLibraryIds(
        edits: List<PlaylistEdit>,
        current: List<String>,
        aliases: MutableMap<String, String>
    ): List<PlaylistEdit> {
        val held = current.toHashSet()
        val named = HashSet<String>()
        edits.forEach { edit -> edit.renamed { id -> id.also { named += it } } }
        // A playlist that gained no library song cannot hold any of them under another id.
        if (held.all { SongId(it).isExternal }) return edits
        for (id in named.filter { SongId(it).isExternal && it !in held && it !in aliases }) {
            val result = api.song(SongId(id))
            if (result is TunesResult.Failure && !result.isNotFound()) throw SendFailed(result)
            val now = (result as? TunesResult.Success)?.value?.id?.value
            if (now != null && now in held) aliases[id] = now
        }
        return edits.map { edit -> edit.renamed { aliases[it] ?: it } }
    }

    private suspend fun done(group: List<PendingChangeEntity>) {
        session.write { group.forEach { dao.remove(it.seq) } }
        changed = changed || group.any { it.kind != ChangeKind.SCROBBLE.name }
    }

    /** Gives up on [group] and says so; the next sync puts the catalog back. */
    private suspend fun drop(group: List<PendingChangeEntity>, deletedOnServer: Boolean) {
        val first = group.first()
        val playlist = ChangeKind.of(first.kind)?.family == ChangeKind.Family.PLAYLIST
        val target = first.targetId.orEmpty()
        session.write {
            // A playlist's rows may have moved to the server id since the group was read.
            val rows = if (playlist) {
                val now = dao.alias(target)?.data()?.removed ?: target
                dao.all().filter {
                    it.targetId == now &&
                        ChangeKind.of(it.kind)?.family == ChangeKind.Family.PLAYLIST
                }
            } else {
                group
            }
            val name = if (playlist) {
                rows.ifEmpty { group }.firstNotNullOfOrNull { it.data().name }
            } else {
                null
            }
            rows.forEach { dao.remove(it.seq) }
            if (deletedOnServer) {
                local.deletePlaylist(target)
            }
            dao.add(
                PendingChangeEntity(
                    kind = ChangeKind.NOTICE.name,
                    targetId = target,
                    payload = PendingPayload(name = name, flag = deletedOnServer).encode(),
                    createdAt = first.createdAt
                )
            )
        }
        changed = true
    }

    private fun <T> TunesResult<T>.orFail(): T = when (this) {
        is TunesResult.Success -> value.also { session.check() }
        is TunesResult.Failure -> throw SendFailed(this)
    }

    private companion object {
        const val MAX_WRITES = 500
    }
}
