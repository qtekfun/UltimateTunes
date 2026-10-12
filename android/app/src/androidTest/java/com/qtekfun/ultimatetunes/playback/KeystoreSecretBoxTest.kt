// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import java.security.KeyStore
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

/** The real Android Keystore box (SPEC §7) on a device, with test-only key aliases. */
class KeystoreSecretBoxTest {
    private val box = KeystoreSecretBox(ALIAS)
    private val plain = "ut-server-config-1\nhttps://music.example/\nutk_secret".encodeToByteArray()

    @After
    fun deleteKeys() {
        KeyStore.getInstance("AndroidKeyStore").apply {
            load(null)
            deleteEntry(ALIAS)
            deleteEntry(OTHER_ALIAS)
        }
    }

    @Test
    fun aSealedSecretOpensAgainAndIsNotStoredInClear() {
        val sealed = box.seal(plain)
        assertFalse(String(sealed, Charsets.ISO_8859_1).contains("utk_secret"))
        assertArrayEquals(plain, box.open(sealed))
        // A fresh IV each time.
        assertFalse(sealed.contentEquals(box.seal(plain)))
    }

    @Test
    fun aTamperedSecretDoesNotOpen() {
        val sealed = box.seal(plain)
        sealed[sealed.size - 1] = (sealed.last().toInt() xor 1).toByte()
        assertNull(box.open(sealed))
        assertNull(box.open(byteArrayOf(1, 2, 3)))
    }

    @Test
    fun withoutItsKeyASecretDoesNotOpen() {
        val sealed = box.seal(plain)
        assertNull(KeystoreSecretBox(OTHER_ALIAS).open(sealed))
        deleteKeys()
        assertNull(box.open(sealed))
    }

    private companion object {
        const val ALIAS = "ut-test-secret-box"
        const val OTHER_ALIAS = "ut-test-secret-box-missing"
    }
}
