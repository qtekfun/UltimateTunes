// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayerSettings
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.settings.PlaybackSettings
import com.qtekfun.ultimatetunes.ui.settings.PlaybackSettingsStore
import java.io.File
import java.nio.file.Path
import java.security.ProviderException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir

/** Reversible and recognisable, so tests can see that nothing is stored in clear. */
private class XorBox(private val mask: Byte = 0x5A) : SecretBox {
    var opened = 0

    override fun seal(plain: ByteArray): ByteArray =
        byteArrayOf(MAGIC) + plain.map { (it.toInt() xor mask.toInt()).toByte() }

    override fun open(sealed: ByteArray): ByteArray? {
        opened++
        if (sealed.firstOrNull() != MAGIC) return null
        return sealed.drop(1).map { (it.toInt() xor mask.toInt()).toByte() }.toByteArray()
    }

    companion object {
        const val MAGIC: Byte = 0x7F
    }
}

private val KEY = ApiKeySecret("utk_" + "a".repeat(43))
private val CONFIG = ServerConfig("https://music.example/base?x=1".toHttpUrl(), KEY)

class ServerConfigVaultTest {
    @TempDir
    lateinit var dir: Path

    private val file get() = File(dir.toFile(), "server.bin")

    @Test
    fun `a saved configuration loads back, sealed on disk`() {
        val vault = ServerConfigVault(file, XorBox())
        assertNull(vault.load())

        vault.save(CONFIG)

        val loaded = vault.load()
        assertEquals("https://music.example/base/", loaded?.root.toString())
        assertEquals(KEY, loaded?.apiKey)
        assertFalse(file.readBytes().decodeToString().contains(KEY.value))
        assertFalse(File(dir.toFile(), "server.bin.tmp").exists())
    }

    @Test
    fun `saving null forgets it`() {
        val vault = ServerConfigVault(file, XorBox())
        vault.save(CONFIG)
        vault.save(null)
        assertFalse(file.exists())
        assertNull(vault.load())
    }

    @Test
    fun `an unopenable or malformed file reads as not connected`() {
        file.writeBytes(byteArrayOf(1, 2, 3))
        assertNull(ServerConfigVault(file, XorBox()).load())

        val box = XorBox()
        for (text in listOf(
            "wrong-format\nhttps://h/\n${KEY.value}",
            "ut-server-config-1\nnot a url\n${KEY.value}",
            "ut-server-config-1\nhttps://h/\nnot-a-key",
            "ut-server-config-1\nhttps://h/"
        )) {
            file.writeBytes(box.seal(text.encodeToByteArray()))
            assertNull(ServerConfigVault(file, box).load(), text)
        }
    }

    @Test
    fun `the test box really changes the bytes`() {
        val box = XorBox()
        val plain = "secret".encodeToByteArray()
        assertFalse(box.seal(plain).contentEquals(plain))
        assertArrayEquals(plain, box.open(box.seal(plain)))
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class ConnectionPersistenceTest {
    @TempDir
    lateinit var dir: Path

    @Test
    fun `restores the saved configuration and saves only confirmed ones`() = runTest {
        val dispatcher = UnconfinedTestDispatcher(testScheduler)
        val file = File(dir.toFile(), "server.bin")
        val box = XorBox()
        val vault = ServerConfigVault(file, box)
        vault.save(CONFIG)

        val source = InMemoryServerConfigSource()
        val gate = ConnectionGate(source)
        val persistence =
            ConnectionPersistence(
                source,
                gate,
                vault,
                CoroutineScope(backgroundScope.coroutineContext + dispatcher),
                dispatcher
            )
        persistence.start()
        assertEquals(CONFIG, source.config.value)

        // A key being checked is never saved; a refused one leaves the old one in place.
        val other = ServerConfig("https://other.example/".toHttpUrl(), KEY)
        gate.tryConfig(other) {
            assertEquals(CONFIG, vault.load())
            TunesResult.NotConfigured
        }
        assertEquals(CONFIG, vault.load())

        // A confirmed one replaces it.
        gate.tryConfig(other) { TunesResult.Success(Unit) }
        assertEquals(other, vault.load())

        // Disconnect forgets it.
        gate.disconnect()
        assertFalse(file.exists())
    }

    @Test
    fun `restore keeps a configuration already set`() {
        val vault = ServerConfigVault(File(dir.toFile(), "server.bin"), XorBox())
        vault.save(CONFIG)
        val other = ServerConfig("https://other.example/".toHttpUrl(), KEY)
        val source = InMemoryServerConfigSource(other)
        val scope = CoroutineScope(Dispatchers.Unconfined)
        ConnectionPersistence(source, ConnectionGate(source), vault, scope, Dispatchers.Unconfined)
            .start()
        assertEquals(other, source.config.value)
        // The configuration in use is the one saved from now on.
        assertEquals(other, vault.load())
        scope.cancel()
    }

    @Test
    fun `a failing Keystore means not connected, never a crash`() {
        val file = File(dir.toFile(), "server.bin")
        ServerConfigVault(file, XorBox()).save(CONFIG)
        val vault = ServerConfigVault(file, ThrowingBox)
        assertNull(vault.load())

        val source = InMemoryServerConfigSource()
        val gate = ConnectionGate(source)
        val scope = CoroutineScope(Dispatchers.Unconfined)
        ConnectionPersistence(source, gate, vault, scope, Dispatchers.Unconfined).start()
        assertNull(source.config.value)

        // Saving a confirmed key fails inside the box: swallowed, the app keeps running.
        source.set(CONFIG)
        assertEquals(CONFIG, source.config.value)
        assertTrue(scope.coroutineContext[Job]!!.isActive)
        scope.cancel()
    }
}

/** A Keystore that is broken: every call throws, as some devices do. */
private object ThrowingBox : SecretBox {
    override fun seal(plain: ByteArray): ByteArray = throw ProviderException("keystore down")

    override fun open(sealed: ByteArray): ByteArray? = throw ProviderException("keystore down")
}

class TrackMappingTest {
    @Test
    fun `tiles and playable tracks map both ways`() {
        val tile = TrackTile(
            id = SongId("yt:AAAAAAAAAAA"),
            title = "T",
            artist = "A",
            album = "Al",
            durationSec = 61,
            coverUrl = "https://h/rest/getCoverArt?id=x",
            isExternal = true,
            albumId = AlbumId("ytalbum:x"),
            trackNumber = 3
        )
        val track = tile.toPlayable()
        assertEquals(61_000L, track.durationMs)
        assertTrue(track.isExternal)
        assertEquals(tile, track.toTile())

        val bare = TrackTile(SongId("x"), "T", "A", null, null, null, false)
        assertEquals(bare, bare.toPlayable().toTile())
    }
}

class SettingsPlayerSourceTest {
    @Test
    fun `the player follows the app's playback settings`() = runTest {
        val store = object : PlaybackSettingsStore {
            override val settings = MutableStateFlow(
                PlaybackSettings(cacheSizeMb = 512, offlineOnly = true, downloadOnWifiOnly = false)
            )

            override suspend fun setCacheSizeMb(value: Int) = Unit

            override suspend fun setOfflineOnly(value: Boolean) = Unit

            override suspend fun setDownloadOnWifiOnly(value: Boolean) = Unit
        }
        assertEquals(
            PlayerSettings(cacheSizeMb = 512, offlineOnly = true, downloadOnWifiOnly = false),
            SettingsPlayerSource(store).settings.first()
        )
    }
}
