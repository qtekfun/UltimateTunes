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
import com.qtekfun.ultimatetunes.core.library.pending.additions
import com.qtekfun.ultimatetunes.core.library.pending.chunk
import com.qtekfun.ultimatetunes.core.library.pending.effectOf
import com.qtekfun.ultimatetunes.core.library.pending.isNotFound
import com.qtekfun.ultimatetunes.core.library.pending.mayBeAboutSongs
import com.qtekfun.ultimatetunes.core.library.pending.mayBeFromCreate
import com.qtekfun.ultimatetunes.core.library.pending.needsAccountCheck
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
        // A disabled account is refused everything: nothing of the queue may go for that.
        val refused = needsAccountCheck(e.failure) && api.me() is TunesResult.Failure
        when (if (refused) FailureEffect.STOP else effectOf(e.failure)) {
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
                create?.let { created(it) }?.let { delete(it.value) }

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
    private suspend fun created(row: PendingChangeEntity): PlaylistId? {
        val data = row.data()
        if (!data.tried) return null
        val asked = Instant.ofEpochMilli(row.createdAt)
        return api.playlists().orFail().firstOrNull {
            it.name == data.name &&
                it.id.value !in data.existing &&
                mayBeFromCreate(it.readonly, it.songCount, it.created, asked)
        }?.id
    }

    /** Makes the playlist, unless an earlier try did and its answer was lost. */
    private suspend fun create(row: PendingChangeEntity): PlaylistId {
        val data = row.data()
        created(row)?.let { return it }
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
        if (edits.isEmpty()) return
        val refused = writeSongs(playlist, edits)
        if (refused.isNotEmpty()) {
            val title = name ?: rows.firstNotNullOfOrNull { it.data().name }
            session.write {
                dao.add(notice(id, rows.first(), PendingPayload(title, ids = refused.toList())))
            }
        }
    }

    private fun notice(target: String, row: PendingChangeEntity, data: PendingPayload) =
        PendingChangeEntity(
            kind = ChangeKind.NOTICE.name,
            targetId = target,
            payload = data.encode(),
            createdAt = row.createdAt
        )

    /**
     * Applies [edits] over what [first] holds and writes the result, reading between writes.
     * Returns the songs the server would not take, which are left out.
     */
    private suspend fun writeSongs(first: Playlist, edits: List<PlaylistEdit>): Set<String> {
        var playlist = first
        var pending = edits
        val aliases = HashMap<String, String>()
        val refused = LinkedHashSet<String>()
        // Each round reads, applies and writes once; more than this means it never settles.
        repeat(MAX_WRITES) {
            val current = playlist.entry.map { it.id.value }
            pending = withLibraryIds(pending, current, aliases)
            val desired = pending.fold(current) { songs, edit -> edit.applyTo(songs) }
            val write = nextWrite(current, desired, limits) ?: return refused
            val result = send(playlist.id, write)
            if (result is TunesResult.Failure) {
                val added = additions(current, desired)
                if (added.isEmpty() || !mayBeAboutSongs(result)) throw SendFailed(result)
                // The playlist itself may be what is gone.
                read(playlist.id.value)
                refused += addApart(playlist.id, added)
                pending = pending.map { it.leavingOut(refused) }
            } else if (write is PlaylistWrite.Replace) {
                // A whole list needs no reading back.
                return refused
            }
            playlist = read(playlist.id.value)
        }
        throw SendFailed(TunesResult.ProtocolError("Playlist did not settle", 0))
    }

    /** Adds [songs] in ever smaller parts and returns those the server refuses on their own. */
    private suspend fun addApart(id: PlaylistId, songs: List<String>): List<String> {
        val fitting = chunk(songs, limits.ids, limits.newSongs).size
        if (fitting < songs.size) {
            return addApart(id, songs.take(fitting)) + addApart(id, songs.drop(fitting))
        }
        session.check()
        val result = api.updatePlaylist(id, songIdsToAdd = songs.map(::SongId))
        return when {
            result !is TunesResult.Failure -> emptyList()

            !mayBeAboutSongs(result) -> throw SendFailed(result)

            songs.size == 1 -> songs

            else -> {
                val half = songs.size / 2
                addApart(id, songs.take(half)) + addApart(id, songs.drop(half))
            }
        }
    }

    private suspend fun send(id: PlaylistId, write: PlaylistWrite): TunesResult<Unit> =
        when (write) {
            is PlaylistWrite.Replace -> api.replacePlaylist(id, write.ids.map(::SongId))

            is PlaylistWrite.Change -> api.updatePlaylist(
                id,
                songIdsToAdd = write.add.map(::SongId),
                songIndexesToRemove = write.removeIndexes
            )
        }.also { session.check() }

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

    /**
     * Gives up on [group] and says so; the next sync puts the catalog back. What was queued while
     * the request was in flight stays, unless it was for a playlist that never got made.
     */
    private suspend fun drop(group: List<PendingChangeEntity>, deletedOnServer: Boolean) {
        val first = group.first()
        val playlist = ChangeKind.of(first.kind)?.family == ChangeKind.Family.PLAYLIST
        val target = first.targetId.orEmpty()
        session.write {
            // A playlist made on the phone may go by its server id by now.
            val now = dao.alias(target)?.data()?.removed ?: target
            val all = dao.all()
            val unmade = all.any { row ->
                row.kind == ChangeKind.CREATE.name && group.any { it.seq == row.seq }
            }
            val gone = if (unmade) all.filter { it.targetId == target } else group
            gone.forEach { dao.remove(it.seq) }
            if (deletedOnServer || unmade) local.deletePlaylist(now)
            val name = if (playlist) group.firstNotNullOfOrNull { it.data().name } else null
            dao.add(notice(target, first, PendingPayload(name = name, flag = deletedOnServer)))
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
