// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import java.net.URLEncoder
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.ValueSource

class ConnectLinkTest {
    // Built at run time, obviously not a real key (no secret scanner should match it).
    private val key = "utk_" + "Ab-_".repeat(10) + "xyz"
    private val httpsOnly = CleartextPolicy { false }
    private val emulatorOnly = CleartextPolicy { it == "10.0.2.2" }

    private fun encode(value: String) = URLEncoder.encode(value, "UTF-8")

    /** What the admin panel writes: `quote(url, safe='')`. */
    private fun link(url: String, key: String = this.key) =
        "ultimatetunes://connect?url=${encode(url)}&key=${encode(key)}"

    private fun parse(link: String, cleartext: CleartextPolicy = httpsOnly) =
        ConnectLink.parse(link, cleartext)

    private fun errorOf(link: String, cleartext: CleartextPolicy = httpsOnly) =
        (parse(link, cleartext) as? ConnectLinkParse.Invalid)?.error

    @Test
    fun `the admin panel's link gives the server root and the key`() {
        val parsed = parse(link("https://music.example.ts.net")) as ConnectLinkParse.Valid

        assertEquals("https://music.example.ts.net/", parsed.url.toString())
        assertEquals(key, parsed.key.value)
    }

    @Test
    fun `a server under a path keeps its path, with a trailing slash`() {
        val parsed = parse(link("https://example.net:8443/tunes")) as ConnectLinkParse.Valid

        assertEquals("https://example.net:8443/tunes/", parsed.url.toString())
    }

    @Test
    fun `parameters may come in any order and the url may be left unencoded`() {
        val parsed = parse("ultimatetunes://connect?key=$key&url=https://music.example.net/")

        assertEquals(
            ConnectLinkParse.Valid(
                (parse(link("https://music.example.net")) as ConnectLinkParse.Valid).url,
                ApiKeySecret(key)
            ),
            parsed
        )
    }

    @Test
    fun `the parsed link never shows the key`() {
        val parsed = parse(link("https://music.example.net"))

        assertFalse(key in parsed.toString())
    }

    @ParameterizedTest
    @ValueSource(
        strings = [
            "https://music.example.net",
            "ultimatetunes:connect?url=https%3A%2F%2Fa.example&key=K",
            "ultimatetunes://connect",
            "ultimatetunes://connect?",
            "UltimateTunes://connect?url=https%3A%2F%2Fa.example&key=K",
            "ultimatetunes://CONNECT?url=https%3A%2F%2Fa.example&key=K",
            "ultimatetunes://other?url=https%3A%2F%2Fa.example&key=K",
            "ultimatetunes://connect/?url=https%3A%2F%2Fa.example&key=K",
            "ultimatetunes://connect.evil.example?url=https%3A%2F%2Fa.example&key=K",
            "otherapp://connect?url=https%3A%2F%2Fa.example&key=K",
            " ultimatetunes://connect?url=https%3A%2F%2Fa.example&key=K"
        ]
    )
    fun `only the ultimatetunes connect scheme and host are accepted`(raw: String) {
        assertEquals(ConnectLinkError.MALFORMED, errorOf(raw.replace("key=K", "key=$key")))
    }

    @ParameterizedTest
    @ValueSource(
        strings = [
            "url=U",
            "key=K",
            "url=U&key=K&extra=1",
            "url=U&key=K&",
            "url=U&url=U&key=K",
            "url=U&key=K&key=K",
            "url=U&key",
            "url&key=K",
            "URL=U&key=K",
            "url=U&key=K#fragment",
            "url=U;key=K",
            "url=U&&key=K"
        ]
    )
    fun `exactly url and key, once each, nothing else`(query: String) {
        val raw = "ultimatetunes://connect?" +
            query.replace("U", encode("https://a.example")).replace("K", key)

        assertEquals(ConnectLinkError.MALFORMED, errorOf(raw))
    }

    @ParameterizedTest
    @ValueSource(strings = ["%", "%4", "%zz", "%C3%28", "%00", "a b", "%0A", "é"])
    fun `broken percent-encoding is refused`(bad: String) {
        val raw = "ultimatetunes://connect?url=${encode("https://a.example")}$bad&key=$key"

        assertEquals(ConnectLinkError.MALFORMED, errorOf(raw))
    }

    @Test
    fun `percent-encoded UTF-8 decodes and plus stays a plus`() {
        assertEquals("é+x/", ConnectLink.percentDecode("%C3%A9+x%2f"))
        assertNull(ConnectLink.percentDecode("%E9"))
    }

    @Test
    fun `an overlong link is refused unread`() {
        val raw = link("https://a.example/" + "p".repeat(ConnectLink.MAX_LENGTH))

        assertEquals(ConnectLinkError.MALFORMED, errorOf(raw))
    }

    @ParameterizedTest
    @ValueSource(
        strings = [
            "",
            "music.example.net",
            "ftp://music.example.net",
            "https://",
            "https://user:pass@music.example.net",
            "https://user@music.example.net",
            "https://music.example.net/?next=1",
            "https://music.example.net/#top",
            "javascript:alert(1)"
        ]
    )
    fun `a url that is not a plain server address is refused`(url: String) {
        assertEquals(ConnectLinkError.INVALID_URL, errorOf(link(url)))
    }

    @Test
    fun `a url with an encoded space is refused`() {
        val raw = "ultimatetunes://connect?url=https%3A%2F%2Fmusic.example.net%20%2F&key=$key"

        assertEquals(ConnectLinkError.INVALID_URL, errorOf(raw))
    }

    @Test
    fun `plain http is refused where cleartext is not permitted`() {
        assertEquals(ConnectLinkError.INSECURE_URL, errorOf(link("http://music.example.net")))
        assertEquals(
            ConnectLinkError.INSECURE_URL,
            errorOf(link("http://music.example.net"), emulatorOnly)
        )
    }

    @Test
    fun `plain http works only for the hosts the cleartext policy allows (debug builds)`() {
        val parsed = parse(link("http://10.0.2.2:8080"), emulatorOnly)

        assertEquals("http://10.0.2.2:8080/", (parsed as ConnectLinkParse.Valid).url.toString())
    }

    @ParameterizedTest
    @ValueSource(
        strings = [
            "",
            "utk_",
            "utk_short",
            "UTK_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_xyz",
            "utk_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_xy+",
            "utk_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_xyzz",
            "utk_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_Ab-_xy="
        ]
    )
    fun `a key that is not in the API key format is refused`(bad: String) {
        assertEquals(ConnectLinkError.INVALID_KEY, errorOf(link("https://a.example", bad)))
    }
}
