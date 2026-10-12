// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import android.os.Bundle
import android.os.Process
import androidx.annotation.OptIn
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaSession
import androidx.test.platform.app.InstrumentationRegistry
import com.qtekfun.ultimatetunes.core.player.session.PlayerAssembly
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import javax.inject.Inject
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Who may change the queue of the playback session (PLAN T17): the app and controllers the system
 * trusts may; any other app gets Media3's restricted command set without the queue commands, so it
 * cannot make the server download.
 */
@OptIn(UnstableApi::class)
@HiltAndroidTest
class SessionAccessTest {
    @get:Rule
    val hilt = HiltAndroidRule(this)

    @Inject
    lateinit var assembly: PlayerAssembly

    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext

    @Before
    fun inject() {
        hilt.inject()
    }

    @Test
    fun onlyTheAppAndTrustedControllersCanChangeTheQueue() {
        val other = commandsFor("org.example.other", trusted = false)
        assertFalse(other.contains(Player.COMMAND_SET_MEDIA_ITEM))
        // Claiming the app's package name from another uid does not help.
        val impostor = commandsFor(context.packageName, trusted = false, uid = Process.myUid() + 1)
        assertFalse(impostor.contains(Player.COMMAND_CHANGE_MEDIA_ITEMS))
        assertFalse(other.contains(Player.COMMAND_SET_MEDIA_ITEM))
        assertFalse(other.contains(Player.COMMAND_CHANGE_MEDIA_ITEMS))

        val ours = commandsFor(context.packageName, trusted = false)
        assertTrue(ours.contains(Player.COMMAND_SET_MEDIA_ITEM))
        assertTrue(ours.contains(Player.COMMAND_CHANGE_MEDIA_ITEMS))

        val system = commandsFor("com.android.systemui", trusted = true)
        assertTrue(system.contains(Player.COMMAND_CHANGE_MEDIA_ITEMS))
    }

    private fun commandsFor(
        packageName: String,
        trusted: Boolean,
        uid: Int = Process.myUid()
    ): Player.Commands {
        lateinit var commands: Player.Commands
        instrumentation.runOnMainSync {
            val player = assembly.newPlayer()
            val session = MediaSession.Builder(context, player).setId("access-$packageName").build()
            val controller = MediaSession.ControllerInfo.createTestOnlyControllerInfo(
                packageName,
                0,
                uid,
                0,
                0,
                trusted,
                Bundle.EMPTY,
                true
            )
            commands = assembly.sessionCallback().onConnect(session, controller)
                .availablePlayerCommands
            session.release()
            player.release()
        }
        return commands
    }
}
