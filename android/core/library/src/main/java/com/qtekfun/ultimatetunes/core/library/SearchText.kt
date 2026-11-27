// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import java.text.Normalizer
import java.util.Locale

/**
 * The form text is stored in for sorting and searching: lowercase, without accents, single spaces.
 * A search normalises what the user typed the same way.
 */
object SearchText {
    private val marks = Regex("\\p{Mn}+")
    private val spaces = Regex("\\s+")

    /** Letters that carry their stroke or ligature in the code point, which NFKD leaves alone. */
    private val plain = mapOf(
        'ø' to "o",
        'ł' to "l",
        'đ' to "d",
        'ħ' to "h",
        'ß' to "ss",
        'æ' to "ae",
        'œ' to "oe"
    )

    /** [parts] (the nulls left out) as one normalised string. */
    fun of(vararg parts: String?): String {
        val joined = parts.filterNotNull().joinToString(" ")
        val bare = Normalizer.normalize(joined, Normalizer.Form.NFKD)
            .replace(marks, "")
            .lowercase(Locale.ROOT)
        return buildString { bare.forEach { append(plain[it] ?: it) } }
            .replace(spaces, " ")
            .trim()
    }
}
