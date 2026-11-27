// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.availability

import coil3.intercept.Interceptor
import coil3.request.ImageResult
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/**
 * The covers of the downloaded songs, kept in their own folder: the image loader's cache may drop
 * them, and with no connection the downloads would then have no artwork. A cover is known by its
 * id alone, so it is found again whatever address reaches the server.
 */
class OfflineCovers(private val folder: File) {
    /** The file names in [folder], so asking for a cover does not read the disk. */
    @Volatile
    private var kept: Set<String> = folder.list().orEmpty().toSet()

    /** The kept cover shown for the cover [url], or null. */
    fun file(url: String): File? {
        val name = coverIdOf(url)?.let(::nameOf) ?: return null
        return if (name in kept) File(folder, name) else null
    }

    /**
     * Makes the folder hold the covers of [ids]: fetches the missing ones with [fetch] (one that
     * cannot be fetched is tried again next time) and deletes the rest.
     */
    suspend fun keep(ids: Set<String>, fetch: suspend (String) -> ByteArray?) {
        val wanted = ids.associateBy(::nameOf)
        folder.mkdirs()
        folder.list().orEmpty().filterNot { it in wanted }.forEach { File(folder, it).delete() }
        kept = folder.list().orEmpty().toSet()
        wanted.filterKeys { it !in kept }.forEach { (name, id) ->
            val bytes = fetch(id)
            if (bytes != null && write(name, bytes)) kept = kept + name
        }
    }

    /** Whole or not at all: a half written cover would never be fetched again. */
    private fun write(name: String, bytes: ByteArray): Boolean = try {
        val part = File(folder, "$name$PART")
        part.writeBytes(bytes)
        part.renameTo(File(folder, name))
    } catch (ignored: IOException) {
        false
    }

    private fun nameOf(id: String): String = MessageDigest.getInstance("SHA-256")
        .digest(id.encodeToByteArray())
        .joinToString("") { "%02x".format(it) }

    companion object {
        private const val PART = ".part"

        /** The cover id of a `getCoverArt` URL; null for any other. */
        fun coverIdOf(url: String): String? = url.toHttpUrlOrNull()
            ?.takeIf { it.pathSegments.lastOrNull()?.startsWith("getCoverArt") == true }
            ?.queryParameter("id")
    }
}

/** Has the image loader read a kept cover from the phone instead of asking the server. */
class OfflineCoverInterceptor(private val covers: OfflineCovers) : Interceptor {
    override suspend fun intercept(chain: Interceptor.Chain): ImageResult {
        val file = (chain.request.data as? String)?.let(covers::file) ?: return chain.proceed()
        return chain.withRequest(chain.request.newBuilder().data(file).build()).proceed()
    }
}
