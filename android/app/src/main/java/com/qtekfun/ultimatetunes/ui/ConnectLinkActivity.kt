// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import com.qtekfun.ultimatetunes.ui.connect.ConnectLinkInbox
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * Receives `ultimatetunes://connect` links (the admin panel's QR code, opened by the camera app)
 * and shows nothing: it hands the link to [ConnectLinkInbox] in memory, opens [MainActivity] with
 * a clean intent and finishes at once. Being excluded from Recents, never kept in history and
 * finished immediately, the link (and its key) does not stay in a task record of ours, whether
 * the link came with `FLAG_ACTIVITY_NEW_TASK` or was started inside the camera app's task.
 * [MainActivity] asks before connecting (`ConnectLinkViewModel`).
 */
@AndroidEntryPoint
class ConnectLinkActivity : ComponentActivity() {
    @Inject
    lateinit var connectLinks: ConnectLinkInbox

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val link = intent?.takeIf { it.action == Intent.ACTION_VIEW }?.dataString
        intent?.data = null
        val replayed = intent?.flags?.and(Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY) != 0
        if (savedInstanceState == null && link != null && !replayed) connectLinks.offer(link)
        // The app's own task, its existing MainActivity if there is one (never a second copy,
        // e.g. when this ran on top of it), with a clean intent.
        startActivity(
            Intent(this, MainActivity::class.java).addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or
                    Intent.FLAG_ACTIVITY_SINGLE_TOP
            )
        )
        finish()
    }
}
