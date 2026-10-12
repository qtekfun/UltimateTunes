// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import java.io.File
import java.io.IOException
import java.security.GeneralSecurityException
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/** Encrypts and decrypts small secrets. */
interface SecretBox {
    fun seal(plain: ByteArray): ByteArray

    /** The plain bytes, or null if [sealed] cannot be opened (other key, tampered, corrupt). */
    fun open(sealed: ByteArray): ByteArray?
}

/**
 * AES-256-GCM with a key that never leaves the Android Keystore (SPEC §7). The sealed form is
 * the 12-byte IV followed by the ciphertext and its tag.
 */
class KeystoreSecretBox(private val alias: String) : SecretBox {
    override fun seal(plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        return cipher.iv + cipher.doFinal(plain)
    }

    override fun open(sealed: ByteArray): ByteArray? = try {
        val key = existingKey()
        if (sealed.size <= IV_BYTES || key == null) {
            null
        } else {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(TAG_BITS, sealed, 0, IV_BYTES))
            cipher.doFinal(sealed, IV_BYTES, sealed.size - IV_BYTES)
        }
    } catch (ignored: GeneralSecurityException) {
        null
    } catch (ignored: IOException) {
        // KeyStore.load can fail with an IOException.
        null
    } catch (
        @Suppress("TooGenericExceptionCaught") ignored: RuntimeException
    ) {
        // Keystore implementations also throw ProviderException, IllegalStateException and
        // others: whatever it is, the saved key cannot be read, so the app is "not connected".
        null
    }

    private fun keyStore() = KeyStore.getInstance(KEYSTORE).apply { load(null) }

    private fun existingKey(): SecretKey? = keyStore().getKey(alias, null) as? SecretKey

    private fun key(): SecretKey = existingKey() ?: KeyGenerator
        .getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        .apply {
            init(
                KeyGenParameterSpec.Builder(
                    alias,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(KEY_BITS)
                    .build()
            )
        }
        .generateKey()

    private companion object {
        const val KEYSTORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
        const val TAG_BITS = 128
        const val KEY_BITS = 256
    }
}

/**
 * The server URL and API key kept across restarts (SPEC §7: the key encrypted with the Android
 * Keystore). Stored as one sealed file; anything unreadable counts as "not connected".
 */
class ServerConfigVault(private val file: File, private val box: SecretBox) {
    /** The saved configuration, or null. */
    fun load(): ServerConfig? {
        val sealed = try {
            if (file.exists()) file.readBytes() else null
        } catch (ignored: IOException) {
            null
        }
        val plain = try {
            sealed?.let(box::open)
        } catch (
            @Suppress("TooGenericExceptionCaught") ignored: RuntimeException
        ) {
            // A box that fails instead of answering null (e.g. ProviderException): not connected.
            null
        }
        return plain?.let { decode(it.decodeToString()) }
    }

    /** Saves [config], or forgets it when null. */
    fun save(config: ServerConfig?) {
        if (config == null) {
            file.delete()
            return
        }
        val text = listOf(FORMAT, config.baseUrl.toString(), config.apiKey.value).joinToString("\n")
        val temp = File(file.parentFile, file.name + ".tmp")
        temp.writeBytes(box.seal(text.encodeToByteArray()))
        if (!temp.renameTo(file)) {
            temp.delete()
            throw IOException("Could not save the server configuration")
        }
    }

    private fun decode(text: String): ServerConfig? {
        val lines = text.split("\n")
        val url = lines.getOrNull(1)?.toHttpUrlOrNull()
        val key = lines.getOrNull(2)?.takeIf(ApiKeySecret::isWellFormed)
        val valid = lines.size == LINES && lines[0] == FORMAT && url != null && key != null
        return if (valid) ServerConfig(url, ApiKeySecret(key)) else null
    }

    private companion object {
        const val FORMAT = "ut-server-config-1"
        const val LINES = 3
    }
}
