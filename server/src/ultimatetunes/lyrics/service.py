# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Lyrics of a song: stored first, LRCLIB on a miss, as OpenSubsonic `structuredLyrics`.

Lookup of a library track:
1. A stored row with lyrics (or a known "no lyrics", e.g. instrumental) is served as is.
2. A stored negative entry (`not_found = 1`) whose `retry_after` has not passed answers an
   empty list without asking LRCLIB.
3. Otherwise LRCLIB is asked, politely: not while a `Retry-After` from LRCLIB is running (one
   global TtlCache entry), not again for a while after this track's lookup failed (one
   TtlCache entry per track), and within our own token bucket (`RateLimiter`, one key for the
   whole server). A refused or failed lookup raises `UpstreamUnavailable` (error 0) when
   nothing is stored, or answers the stale negative entry (empty list) when one exists.
4. Found → stored (`source = 'lrclib'`, `source_ref` = the LRCLIB record id). 404, or a record
   that is not instrumental but has neither synced nor plain lyrics → stored as a negative
   entry retried after `lyrics_not_found_retry_days`.

External songs (`yt:` ids without a library track) have no row to store into: they answer an
empty list and LRCLIB is not asked (SPEC §11, T10).

Payload: synced lyrics first (`synced: true`, `start` in ms, the LRC `[offset:]` and the row's
`offset_ms` already applied to the starts, so no `offset` is sent), then plain lyrics
(`synced: false`) if stored. When the stored LRC has no valid time tag at all and no plain
text is stored, its text lines are served as plain lyrics. `lang` is the row's (`und`).
"""

import logging
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING

from ultimatetunes.core.cache import TtlCache
from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.core.ratelimit import Limit, RateLimiter
from ultimatetunes.db.database import Database
from ultimatetunes.errors import UpstreamUnavailable
from ultimatetunes.lyrics.fake import FakeLrclib
from ultimatetunes.lyrics.lrc import parse_lrc, plain_lines
from ultimatetunes.lyrics.lrclib import (
    LrclibClient,
    LrclibQuery,
    LrclibRecord,
    LrclibThrottled,
    LrclibUnavailable,
    LyricsSource,
)
from ultimatetunes.lyrics.repository import LyricsRepository, LyricsTrack, StoredLyrics
from ultimatetunes.lyrics.settings import LyricsSettings

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services

log = logging.getLogger(__name__)

RATE_KEY = "lrclib:global"
BACKOFF_KEY = "lyrics:lrclib:backoff"
FAILED_KEY = "lyrics:lrclib:failed:"
SOURCE = "lrclib"

LyricsPayload = list[dict[str, object]]


@dataclass(frozen=True)
class _Outcome:
    record: LrclibRecord | None


@dataclass
class LyricsService:
    db: Database
    cache: TtlCache
    rate_limiter: RateLimiter
    clock: Clock
    client: LyricsSource
    settings: LyricsSettings

    @property
    def _limit(self) -> Limit:
        return Limit(self.settings.lyrics_rate_per_s, self.settings.lyrics_burst)

    def structured_lyrics(self, song_id: str) -> LyricsPayload:
        """The `structuredLyrics` list of `song_id` (empty when none are known)."""
        with self.db.read() as conn:
            repo = LyricsRepository(conn)
            track = repo.resolve_song(song_id)
            stored = None if track is None else repo.lyrics(track.id)
        if track is None:
            return []
        if stored is not None and not stored.not_found:
            return render(track, stored)
        if stored is not None and not self._due(stored):
            return []
        try:
            outcome = self._lookup(track)
        except UpstreamUnavailable:
            if stored is not None:
                return []
            raise
        if outcome is None:
            return []
        saved = self._save(track, outcome)
        return [] if saved.not_found else render(track, saved)

    def _due(self, stored: StoredLyrics) -> bool:
        return stored.retry_after is None or stored.retry_after <= format_ts(self.clock.now())

    def _lookup(self, track: LyricsTrack) -> _Outcome | None:
        """Asks LRCLIB. `None` when the track cannot be looked up at all (no title or artist)."""
        title, artist = track.title.strip(), track.artist_name.strip()
        if not title or not artist:
            return None
        failed_key = FAILED_KEY + track.id
        if self.cache.get(BACKOFF_KEY) is not None or self.cache.get(failed_key) is not None:
            raise UpstreamUnavailable("Lyrics are unavailable right now, try again later")
        if not self.rate_limiter.hit(RATE_KEY, self._limit).allowed:
            raise UpstreamUnavailable("Too many lyrics lookups right now, try again later")
        duration = None if track.duration_ms is None else round(track.duration_ms / 1000)
        query = LrclibQuery(title, artist, (track.album_name or "").strip() or None, duration)
        try:
            return _Outcome(self.client.get(query))
        except LrclibThrottled as error:
            log.warning("LRCLIB throttled lookups for %d s", error.retry_after_s)
            self.cache.set(BACKOFF_KEY, "1", error.retry_after_s)
            raise
        except LrclibUnavailable as error:
            log.warning("LRCLIB lookup failed: %s", error.message)
            self.cache.set(failed_key, "1", self.settings.lyrics_failure_backoff_s)
            raise

    def _save(self, track: LyricsTrack, outcome: _Outcome) -> StoredLyrics:
        now = self.clock.now()
        record = outcome.record
        if record is not None and not record.instrumental and not _has_text(record):
            record = None  # a record without lyrics: retried later, like a 404
        row = StoredLyrics(
            track_id=track.id,
            source=SOURCE,
            source_ref=None,
            lang="und",
            synced_lrc=None,
            plain_text=None,
            offset_ms=0,
            not_found=record is None,
            fetched_at=format_ts(now),
            retry_after=None,
        )
        if record is None:
            retry = now + timedelta(days=self.settings.lyrics_not_found_retry_days)
            row = replace(row, retry_after=format_ts(retry))
        elif not record.instrumental:
            row = replace(
                row,
                source_ref=str(record.id),
                synced_lrc=record.synced_lyrics,
                plain_text=record.plain_lyrics,
            )
        else:
            row = replace(row, source_ref=str(record.id))
        with self.db.transaction() as conn:
            LyricsRepository(conn).save(row)
        return row


def _has_text(record: LrclibRecord) -> bool:
    return bool((record.synced_lyrics or "").strip() or (record.plain_lyrics or "").strip())


def _entry(track: LyricsTrack, lang: str, synced: bool, lines: object) -> dict[str, object]:
    return {
        "displayArtist": track.artist_name,
        "displayTitle": track.title,
        "lang": lang,
        "synced": synced,
        "line": lines,
    }


def render(track: LyricsTrack, stored: StoredLyrics) -> LyricsPayload:
    """`structuredLyrics` of a stored row: synced first, then plain."""
    result: LyricsPayload = []
    plain = stored.plain_text
    if stored.synced_lrc:
        parsed = parse_lrc(stored.synced_lrc)
        if parsed.lines:
            lines = [
                {"start": max(0, line.start_ms - stored.offset_ms), "value": line.text}
                for line in parsed.lines
            ]
            result.append(_entry(track, stored.lang, True, lines))
        elif not plain and parsed.untimed:
            plain = "\n".join(parsed.untimed)
    if plain:
        texts = plain_lines(plain)
        if texts:
            result.append(_entry(track, stored.lang, False, [{"value": t} for t in texts]))
    return result


def build_lyrics_service(
    services: "Services", settings: LyricsSettings | None = None
) -> LyricsService:
    """The service over the api's shared `Services` (cheap: no connection is opened here)."""
    settings = settings or LyricsSettings()
    client: LyricsSource = LrclibClient(timeout_s=settings.lyrics_timeout_s)
    if services.settings.fake_youtube:
        # The test stack never reaches LRCLIB (like the fake catalog and downloader).
        client = FakeLrclib()
    return LyricsService(
        db=services.db,
        cache=services.cache,
        rate_limiter=services.rate_limiter,
        clock=services.clock,
        client=client,
        settings=settings,
    )
