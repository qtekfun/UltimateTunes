// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.demo

import com.qtekfun.ultimatetunes.core.api.model.Import
import com.qtekfun.ultimatetunes.core.api.model.ImportId
import com.qtekfun.ultimatetunes.core.api.model.ImportItem
import com.qtekfun.ultimatetunes.core.api.model.ImportItemState
import com.qtekfun.ultimatetunes.core.api.model.ImportSource
import com.qtekfun.ultimatetunes.core.api.model.ImportState
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.demo.DemoCatalog.toTrackItem
import java.time.Clock
import java.time.Duration
import java.time.Instant

/**
 * The demo's playlist imports: each one "runs" for [RUN_TIME] after it is created, reading and
 * then matching its rows one by one against [DemoCatalog] (a few rows are not found), and once
 * done adds a playlist through [onDone]. One finished import is there from the start.
 */
@Suppress("MagicNumber") // Invented timings and row counts.
internal class DemoImports(private val clock: Clock, private val onDone: (Import) -> PlaylistId) {
    private class Run(
        val id: ImportId,
        val source: ImportSource,
        val sourceUrl: String?,
        val name: String,
        val createdAt: Instant,
        val rows: List<Row>,
        var playlistId: PlaylistId? = null
    )

    /** A source row: what the file or playlist said, and the demo song it matches (or none). */
    private class Row(val title: String, val artist: String, val songId: String?)

    private val lock = Any()
    private val runs = mutableListOf<Run>()

    init {
        val first =
            newRun(
                ImportSource.YTMUSIC,
                "https://music.youtube.com/playlist?list=demo",
                "Road Trip Mix"
            )
        synchronized(lock) {
            runs += first
            // Created long enough ago to be finished: this also adds its playlist.
            snapshot(first, withItems = true)
        }
    }

    /** Starts an import; [name] defaults to a source-specific name like the server's. */
    fun create(source: ImportSource, sourceUrl: String?, name: String?): Import =
        synchronized(lock) {
            val run = newRun(source, sourceUrl, name ?: defaultName(source), clock.instant())
            runs += run
            snapshot(run, withItems = false)
        }

    fun list(limit: Int?, offset: Int?): List<Import> = synchronized(lock) {
        runs.sortedByDescending { it.createdAt }
            .drop(offset ?: 0)
            .take(limit ?: runs.size)
            .map { snapshot(it, withItems = false) }
    }

    fun get(id: String): Import? = synchronized(lock) {
        runs.firstOrNull { it.id.value == id }?.let { snapshot(it, withItems = true) }
    }

    private fun defaultName(source: ImportSource): String = when (source) {
        ImportSource.YTMUSIC -> "Imported Playlist"
        else -> "Imported File"
    }

    private fun newRun(
        source: ImportSource,
        sourceUrl: String?,
        name: String,
        createdAt: Instant = clock.instant().minus(RUN_TIME.multipliedBy(10))
    ): Run {
        val songs = DemoCatalog.songs.shuffled().take(MATCHED_ROWS)
        val rows = songs.map { Row(it.title, it.artist.orEmpty(), it.id.value) } +
            NOT_FOUND.map { (title, artist) -> Row(title, artist, null) }
        return Run(
            id = ImportId("0199e0de-0005-7000-8000-%012x".format(runs.size + 1)),
            source = source,
            sourceUrl = sourceUrl,
            name = name,
            createdAt = createdAt,
            rows = rows.shuffled()
        )
    }

    /** How many rows are decided at this moment (all once [RUN_TIME] has passed). */
    private fun decided(run: Run): Int {
        val elapsed = Duration.between(run.createdAt, clock.instant())
        val matching = elapsed.minus(READING_TIME)
        if (matching.isNegative) return 0
        val perRow = RUN_TIME.minus(READING_TIME).toMillis() / run.rows.size
        return (matching.toMillis() / perRow).toInt().coerceAtMost(run.rows.size)
    }

    private fun itemsOf(run: Run, decided: Int): List<ImportItem> = run.rows.mapIndexed { i, row ->
        val song = row.songId?.let(DemoCatalog::song)?.takeIf { i < decided }
        ImportItem(
            position = i + 1,
            sourceTitle = row.title,
            sourceArtist = row.artist,
            state = when {
                i >= decided -> ImportItemState.PENDING
                song != null -> ImportItemState.MATCHED
                else -> ImportItemState.NOT_FOUND
            },
            matchScore = song?.let { MATCH_SCORE },
            track = song?.toTrackItem()
        )
    }

    private fun snapshot(run: Run, withItems: Boolean): Import {
        val elapsed = Duration.between(run.createdAt, clock.instant())
        val decided = decided(run)
        val done = decided == run.rows.size
        val state = when {
            done -> ImportState.DONE
            elapsed < QUEUED_TIME -> ImportState.QUEUED
            elapsed < READING_TIME -> ImportState.READING
            else -> ImportState.MATCHING
        }
        val items = itemsOf(run, decided)
        val decidedItems = items.take(decided)
        val import = Import(
            id = run.id,
            source = run.source,
            sourceUrl = run.sourceUrl,
            name = run.name,
            state = state,
            total = if (state == ImportState.QUEUED) 0 else run.rows.size,
            matched = decidedItems.count { it.state == ImportItemState.MATCHED },
            notFound = decidedItems.count { it.state == ImportItemState.NOT_FOUND },
            progress = decided.toDouble() / run.rows.size,
            playlistId = run.playlistId,
            createdAt = run.createdAt,
            updatedAt = minOf(clock.instant(), run.createdAt.plus(RUN_TIME)),
            finishedAt = if (done) run.createdAt.plus(RUN_TIME) else null,
            items = if (withItems) items else emptyList()
        )
        if (done && run.playlistId == null) {
            run.playlistId = onDone(import.copy(items = items))
            return import.copy(playlistId = run.playlistId)
        }
        return import
    }

    companion object {
        val RUN_TIME: Duration = Duration.ofSeconds(12)
        private val QUEUED_TIME: Duration = Duration.ofSeconds(1)
        private val READING_TIME: Duration = Duration.ofSeconds(2)
        private const val MATCHED_ROWS = 10
        private const val MATCH_SCORE = 0.97
        private val NOT_FOUND = listOf(
            "Whistle in the Attic" to "Unknown Busker",
            "Untitled Demo 4" to "The Garage Tapes"
        )
    }
}
