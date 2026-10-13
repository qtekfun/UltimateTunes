# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The encrypted YouTube cookies store (D14).

One row in the `settings` table (`youtube.cookies.v1`) holds a JSON object with the Fernet
ciphertext of the cookies text and a **non-secret** status (when it was set, how many cookies,
whether a youtube.com cookie is present). Status reads that JSON without decrypting; only the
worker's claim decrypts it. The cookies text is never logged and never put in the JSON in clear.
"""

import json
from dataclasses import dataclass

from ultimatetunes.auth.secretbox import SecretBox
from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.db.database import Database
from ultimatetunes.db.repository import Repository
from ultimatetunes.errors import InvalidParameter
from ultimatetunes.youtube.settings import YouTubeSettings

SETTING_KEY = "youtube.cookies.v1"
# The headers a Netscape/Mozilla cookies.txt starts with (yt-dlp requires one of them).
NETSCAPE_MAGICS = ("# Netscape HTTP Cookie File", "# HTTP Cookie File")
# A cookie line has seven tab-separated fields; some exporters prefix one with `#HttpOnly_`.
COOKIE_FIELDS = 7
HTTP_ONLY_PREFIX = "#HttpOnly_"


@dataclass(frozen=True)
class CookieStatus:
    configured: bool
    set_at: str | None = None
    cookie_count: int | None = None
    has_youtube_domain: bool | None = None


def validate_netscape(text: str) -> tuple[int, bool]:
    """`(cookie_count, has_youtube_domain)` for a well-formed Netscape cookies.txt, else
    `InvalidParameter`. Every non-blank line is either a comment or a seven-field tab-separated
    cookie line; the magic header must be present and at least one cookie line must exist. The
    content (cookie values) never reaches the error message."""
    # Split only on \n after normalising \r\n, as yt-dlp's cookiejar reads the file; splitlines()
    # would also break on \x0b, \x0c, \x85 and U+2028, which a validator must not accept.
    lines = text.replace("\r\n", "\n").split("\n")
    if not any(line.strip() in NETSCAPE_MAGICS for line in lines):
        raise InvalidParameter("Not a Netscape cookies.txt (missing its header line)")
    count = 0
    youtube = False
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.startswith("#") and not line.startswith(HTTP_ONLY_PREFIX):
            continue
        body = line[len(HTTP_ONLY_PREFIX) :] if line.startswith(HTTP_ONLY_PREFIX) else line
        fields = body.split("\t")
        if len(fields) != COOKIE_FIELDS:
            raise InvalidParameter("Not a Netscape cookies.txt (a line is not tab-separated)")
        if not fields[4].strip().isdigit() and fields[4].strip() not in ("", "0"):
            raise InvalidParameter("Not a Netscape cookies.txt (a bad expiry field)")
        count += 1
        if "youtube.com" in fields[0].lower():
            youtube = True
    if count == 0:
        raise InvalidParameter("Not a Netscape cookies.txt (no cookie lines)")
    return count, youtube


class _SettingsRepo(Repository):
    @dataclass(frozen=True)
    class _Value:
        value: str

    def get(self) -> str | None:
        row = self.one(self._Value, "SELECT value FROM settings WHERE key = ?", (SETTING_KEY,))
        return None if row is None else row.value

    def put(self, value: str, now: str) -> None:
        if self.run(
            "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?", (value, now, SETTING_KEY)
        ):
            return
        self.run(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (SETTING_KEY, value, now),
        )

    def delete(self) -> None:
        self.run("DELETE FROM settings WHERE key = ?", (SETTING_KEY,))


class YouTubeCookieStore:
    """Validates, seals, reads and clears the server-wide YouTube cookies."""

    def __init__(self, db: Database, clock: Clock, settings: YouTubeSettings | None = None) -> None:
        self._db = db
        self._clock = clock
        self._settings = settings or YouTubeSettings()
        self._box = SecretBox(self._settings.ytdlp_cookies_key)

    @property
    def available(self) -> bool:
        """Whether an encryption key is configured (else the feature fails closed)."""
        return self._box.available

    @property
    def max_bytes(self) -> int:
        return self._settings.ytdlp_cookies_max_bytes

    def set(self, text: str) -> CookieStatus:
        """Validate, seal and store the cookies. Raises `InvalidParameter` for a bad format and
        `FeatureDisabled` when no key is configured. The text never reaches a log."""
        count, youtube = validate_netscape(text)
        sealed = self._box.encrypt(text)  # FeatureDisabled when UT_YTDLP_COOKIES_KEY is unset
        now = format_ts(self._clock.now())
        record = json.dumps(
            {"sealed": sealed, "set_at": now, "count": count, "youtube": youtube},
            separators=(",", ":"),
        )
        with self._db.transaction() as conn:
            _SettingsRepo(conn).put(record, now)
        return CookieStatus(True, now, count, youtube)

    def clear(self) -> None:
        with self._db.transaction() as conn:
            _SettingsRepo(conn).delete()

    def status(self) -> CookieStatus:
        """The non-secret status, without decrypting anything."""
        record = self._load()
        if record is None:
            return CookieStatus(False)
        set_at = record.get("set_at")
        count = record.get("count")
        youtube = record.get("youtube")
        return CookieStatus(
            configured=True,
            set_at=set_at if isinstance(set_at, str) else None,
            cookie_count=count if isinstance(count, int) else None,
            has_youtube_domain=None if youtube is None else bool(youtube),
        )

    def current(self) -> str | None:
        """The decrypted cookies text, or None when none are stored. Raises on a wrong or
        missing key (fail closed; a stored blob is never used as plaintext)."""
        record = self._load()
        if record is None or not record.get("sealed"):
            return None
        return self._box.decrypt(str(record["sealed"]))

    def _load(self) -> dict[str, object] | None:
        with self._db.read() as conn:
            raw = _SettingsRepo(conn).get()
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except ValueError:  # a corrupt row: treated as no cookies, never an error
            return None
        return parsed if isinstance(parsed, dict) else None
