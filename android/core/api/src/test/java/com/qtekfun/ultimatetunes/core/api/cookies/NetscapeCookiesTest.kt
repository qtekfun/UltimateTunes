// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.cookies

import java.time.Instant
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/** Invented cookie names and values only. */
class NetscapeCookiesTest {
    private val now = Instant.parse("2026-10-13T00:00:00Z")
    private val expiry = now.plus(NetscapeCookies.SESSION_LIFETIME).epochSecond

    private fun youtube(header: String?) =
        NetscapeCookies.Source(header, ".youtube.com", "www.youtube.com")

    private fun google(header: String?) =
        NetscapeCookies.Source(header, ".google.com", "accounts.google.com")

    @Test
    fun `the header line, then seven tab separated fields per cookie`() {
        val text = NetscapeCookies.serialize(listOf(youtube("SID=abc; HSID=def")), now)!!

        val lines = text.trimEnd('\n').split('\n')
        assertEquals(NetscapeCookies.HEADER, lines[0])
        assertEquals(3, lines.size)
        assertEquals(".youtube.com\tTRUE\t/\tTRUE\t$expiry\tSID\tabc", lines[1])
        assertEquals(".youtube.com\tTRUE\t/\tTRUE\t$expiry\tHSID\tdef", lines[2])
        assertTrue(lines.drop(1).all { it.split('\t').size == 7 })
        assertTrue(text.endsWith("\n"))
    }

    @Test
    fun `values keep their equals signs and spaces inside`() {
        val text = NetscapeCookies.serialize(listOf(youtube("LOGIN_INFO=AFmm=:AB==; X=a b")), now)!!

        assertTrue(text.contains("\tLOGIN_INFO\tAFmm=:AB==\n"))
        assertTrue(text.contains("\tX\ta b\n"))
    }

    @Test
    fun `youtube and google cookies get their own domains, the first source wins`() {
        val text = NetscapeCookies.serialize(
            listOf(
                youtube("SID=y1"),
                google("SID=g1; SIDCC=g2"),
                google("SID=other"),
                youtube("SID=y2")
            ),
            now
        )!!

        val lines = text.trimEnd('\n').split('\n').drop(1)
        assertEquals(
            listOf(
                ".youtube.com\tTRUE\t/\tTRUE\t$expiry\tSID\ty1",
                ".google.com\tTRUE\t/\tTRUE\t$expiry\tSID\tg1",
                ".google.com\tTRUE\t/\tTRUE\t$expiry\tSIDCC\tg2"
            ),
            lines
        )
    }

    @Test
    fun `__Host- cookies are host only`() {
        val text = NetscapeCookies.serialize(listOf(google("__Host-GAPS=1:z")), now)!!

        assertTrue(
            text.contains("accounts.google.com\tFALSE\t/\tTRUE\t$expiry\t__Host-GAPS\t1:z\n")
        )
    }

    @Test
    fun `malformed pieces are dropped`() {
        val header = "good=1; =novalue; noequals; ; bad\tname=2; ok=3\tx; last="
        assertEquals(listOf("good" to "1", "last" to ""), NetscapeCookies.parseHeader(header))
    }

    @Test
    fun `no cookie means no file`() {
        assertNull(NetscapeCookies.serialize(emptyList(), now))
        assertNull(NetscapeCookies.serialize(listOf(youtube(null), google("  ;")), now))
    }

    @Test
    fun `output stops before the size limit the server enforces`() {
        val big = (1..100_000).joinToString("; ") { "c$it=${"v".repeat(20)}" }

        val text = NetscapeCookies.serialize(listOf(youtube(big)), now)!!

        assertTrue(text.toByteArray().size <= NetscapeCookies.MAX_BYTES)
        assertTrue(text.endsWith("\n"))
        assertTrue(text.contains("\tc1\t"))
    }

    @Test
    fun `only a SAPISID type cookie is a signed in session`() {
        assertFalse(NetscapeCookies.hasSession(null))
        assertFalse(NetscapeCookies.hasSession("VISITOR_INFO1_LIVE=a; YSC=b; SID=c"))
        assertTrue(NetscapeCookies.hasSession("YSC=b; SAPISID=x"))
        assertTrue(NetscapeCookies.hasSession("__Secure-3PAPISID=x"))
        assertTrue(NetscapeCookies.hasSession("__Secure-3PSID=x"))
    }

    @Test
    fun `a source never prints its cookies`() {
        assertEquals(
            "Source(domain=.youtube.com, host=www.youtube.com)",
            youtube("SID=secret").toString()
        )
    }
}
