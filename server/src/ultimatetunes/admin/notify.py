# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Notifications of failed downloads and canary runs (SPEC RF-13) to one URL the admin set.

The target lives in the runtime `settings` table: a kind (`ntfy`: plain text with a `Title`
header, as ntfy topics expect; `webhook`: a small JSON document) and an **https** URL without
credentials in it. It is the only outbound host the panel ever contacts (CLAUDE.md), with no
redirects followed and a short timeout. A host name is resolved again right before each send,
and the send is refused when any address it resolves to is loopback, link-local, unspecified
or multicast (audit L6: a public name pointing at the server itself or at cloud metadata);
LAN addresses stay allowed for a self-hosted ntfy. httpx resolves once more when it connects,
so a name re-pointed within that instant (DNS rebinding) is a residual risk the short window
and the admin-only setting keep small. The URL is never logged (an ntfy topic name is a
secret of sorts); only its host is.

`NotificationSweep` runs in the api: every `UT_ADMIN_NOTIFY_INTERVAL_S` it collects the jobs
that failed and the canary runs that failed since its cursor (also in `settings`), moves the
cursor with a compare-and-set (so with several replicas one of them sends), then sends one
message. It also says when downloads were paused for low disk space (`jobs.gate.LOW_DISK_KEY`)
since the cursor. Nothing is sent before a target is configured, and configuring one starts
the cursor at that moment (no backlog).
"""

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx
from starlette.concurrency import run_in_threadpool

from ultimatetunes.admin.repository import AdminRepository
from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.db.database import Database
from ultimatetunes.errors import InvalidParameter
from ultimatetunes.jobs.gate import LOW_DISK_KEY

log = logging.getLogger(__name__)

Kind = Literal["ntfy", "webhook"]
KINDS: tuple[Kind, ...] = ("ntfy", "webhook")
KEY_KIND = "admin.notify.kind"
KEY_URL = "admin.notify.url"
KEY_CURSOR = "admin.notify.cursor"
MAX_URL_LENGTH = 2048
TIMEOUT_S = 10.0
# At most this many items are listed in one message (the count is always exact).
MAX_LISTED = 10


@dataclass(frozen=True)
class Target:
    kind: Kind
    url: str

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or "?"


@dataclass(frozen=True)
class Message:
    title: str
    body: str


def check_url(url: str) -> str:
    """An absolute https URL with a host and no user or password in it."""
    cleaned = url.strip()
    if not cleaned or len(cleaned) > MAX_URL_LENGTH or not cleaned.isprintable():
        raise InvalidParameter("The URL is empty or too long")
    parts = urlsplit(cleaned)
    if parts.scheme != "https" or not parts.hostname:
        raise InvalidParameter("The URL must start with https://")
    if parts.username is not None or parts.password is not None:
        raise InvalidParameter("The URL must not contain a user or password")
    if any(c in cleaned for c in " \t\r\n"):
        raise InvalidParameter("The URL must not contain spaces")
    if _own_host(parts.hostname):
        raise InvalidParameter("Notifications cannot go to this server's own network")
    return cleaned


def _own_host(host: str) -> bool:
    """Loopback, link-local (cloud metadata), unspecified and multicast addresses, and
    `localhost` names. Checked on save and again on every send, where `Sender` also checks
    every address the name resolves to; LAN addresses stay allowed for a self-hosted ntfy."""
    name = host.rstrip(".").lower()
    if name == "localhost" or name.endswith(".localhost"):
        return True
    address = _ip(name)
    return address is not None and _own_address(address)


def _ip(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return None


def _own_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(address, "ipv4_mapped", None)
    address = mapped or address
    return (
        address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_multicast
    )


def check_kind(kind: str) -> Kind:
    for known in KINDS:
        if kind == known:
            return known
    raise InvalidParameter("Unknown notification kind")


def load_target(db: Database) -> Target | None:
    with db.read() as conn:
        repo = AdminRepository(conn)
        kind, url = repo.setting(KEY_KIND), repo.setting(KEY_URL)
    if kind not in KINDS or not url:
        return None
    return Target(check_kind(kind), url)


def save_target(db: Database, clock: Clock, target: Target | None) -> None:
    now = format_ts(clock.now())
    with db.transaction() as conn:
        repo = AdminRepository(conn)
        if target is None:
            for key in (KEY_KIND, KEY_URL, KEY_CURSOR):
                repo.delete_setting(key)
            return
        repo.put_setting(KEY_KIND, target.kind, now)
        repo.put_setting(KEY_URL, target.url, now)
        if repo.setting(KEY_CURSOR) is None:
            repo.put_setting(KEY_CURSOR, now, now)


Resolver = Callable[[str], Awaitable[list[str]]]


async def system_resolve(host: str) -> list[str]:
    """Every address `host` resolves to (the system resolver, as httpx will use it)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


class Sender:
    """Posts one message to the target. Errors are logged, never raised to the caller."""

    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, resolve: Resolver | None = None
    ) -> None:
        self._transport = transport
        self._resolve = resolve or system_resolve

    async def _resolves_safely(self, target: Target) -> bool:
        """False (logged) when the host does not resolve, or resolves to an address of this
        server's own network. IP literals were already checked by `check_url`."""
        host = target.host
        if _ip(host) is not None:
            return True
        try:
            addresses = await self._resolve(host)
        except OSError:
            log.warning("notification to %s failed: the name does not resolve", host)
            return False
        parsed = [_ip(a) for a in addresses]
        if not parsed or any(a is None or _own_address(a) for a in parsed):
            log.warning("notification to %s refused: it resolves to this server's network", host)
            return False
        return True

    async def send(self, target: Target, message: Message) -> bool:
        if target.kind == "ntfy":
            request: dict[str, object] = {
                "content": message.body.encode(),
                "headers": {"Title": _header_safe(message.title), "Tags": "warning"},
            }
        else:
            request = {
                "json": {"source": "ultimatetunes", "title": message.title, "message": message.body}
            }
        try:
            url = check_url(target.url)
        except InvalidParameter as exc:
            log.warning("notification to %s failed: %s", target.host, type(exc).__name__)
            return False
        if not await self._resolves_safely(target):
            return False
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=TIMEOUT_S, follow_redirects=False
            ) as client:
                response = await client.post(url, **request)  # type: ignore[arg-type]
        except httpx.HTTPError as exc:
            log.warning("notification to %s failed: %s", target.host, type(exc).__name__)
            return False
        if response.is_success:
            return True
        log.warning("notification to %s answered HTTP %d", target.host, response.status_code)
        return False


def _header_safe(text: str) -> str:
    """ntfy reads the title from a header: ASCII only, no line breaks."""
    return text.encode("ascii", "replace").decode().replace("\r", " ").replace("\n", " ")


def compose(
    jobs: list[tuple[str, str, str | None]],
    canaries: list[tuple[str, str | None]],
    low_disk_since: str | None = None,
) -> Message | None:
    if not jobs and not canaries and low_disk_since is None:
        return None
    lines: list[str] = []
    if low_disk_since is not None:
        lines.append(
            f"Downloads paused since {low_disk_since}: less than UT_MIN_FREE_BYTES free on"
            " /music or /staging."
        )
    if jobs:
        lines.append(f"{len(jobs)} download(s) failed:")
        lines.extend(
            f"- {artist} - {title}" + (f" ({code})" if code else "")
            for title, artist, code in jobs[:MAX_LISTED]
        )
    if canaries:
        lines.append(f"{len(canaries)} canary run(s) failed:")
        lines.extend(f"- {source}: {msg or 'no message'}" for source, msg in canaries[:MAX_LISTED])
    return Message("UltimateTunes: something failed", "\n".join(lines))


class NotificationSweep:
    def __init__(self, db: Database, clock: Clock, sender: Sender) -> None:
        self._db = db
        self._clock = clock
        self._sender = sender

    def _collect(self) -> tuple[Target, Message] | None:
        target = load_target(self._db)
        if target is None:
            return None
        now = format_ts(self._clock.now())
        with self._db.transaction() as conn:
            repo = AdminRepository(conn)
            cursor = repo.setting(KEY_CURSOR)
            if cursor is None:
                repo.put_setting(KEY_CURSOR, now, now)
                return None
            low_disk = repo.setting(LOW_DISK_KEY)
            message = compose(
                repo.failed_jobs_between(cursor, now),
                repo.failed_canaries_between(cursor, now),
                low_disk if low_disk is not None and cursor < low_disk <= now else None,
            )
            if not repo.swap_setting(KEY_CURSOR, cursor, now, now) or message is None:
                return None
        return target, message

    async def run_once(self) -> bool:
        """True when a message was sent."""
        collected = await run_in_threadpool(self._collect)
        if collected is None:
            return False
        return await self._sender.send(*collected)

    async def run_forever(self, interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            try:
                await self.run_once()
            except Exception:
                # One failed sweep (database busy, ...) must never stop the next ones.
                log.exception("notification sweep failed")
