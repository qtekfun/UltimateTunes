// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.buildlogic

private val VERSION = Regex("""(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?""")

/** Google Play's (and therefore Android's practical) upper bound for a version code. */
private const val MAX_VERSION_CODE = 2_100_000_000L

/** The two-digit slot of MINOR, PATCH and the release candidate number. */
private const val SLOT = 100

/** The release-candidate slot of a final release, which sorts it after all its candidates. */
private const val FINAL = 99

/** Release candidates are numbered 1..98 (99 is the final release). */
private const val LAST_RC = 98
private val RC_RANGE = 1..LAST_RC

/**
 * The Android version code of [version], the content of the repository's `VERSION` file
 * (`MAJOR.MINOR.PATCH` or `MAJOR.MINOR.PATCH-rc.N`), so it never depends on dates or the machine:
 * `(MAJOR*10000 + MINOR*100 + PATCH)*100 + N`, with N = 99 for a final release. Same formula as
 * `tools/version-code.sh`: `1.0.0-rc.1` -> 1000001, `1.0.0` -> 1000099.
 *
 * @throws IllegalArgumentException if [version] is not of that form or does not fit.
 */
fun versionCodeOf(version: String): Int {
    val match = requireNotNull(VERSION.matchEntire(version)) {
        "VERSION must be MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-rc.N: '$version'"
    }
    val (major, minor, patch) = match.destructured
    val rc = match.groupValues.last()
    require(minor.toInt() < SLOT && patch.toInt() < SLOT) {
        "MINOR and PATCH must be below $SLOT: '$version'"
    }
    require(rc.isEmpty() || rc.toInt() in RC_RANGE) {
        "The release candidate number must be in $RC_RANGE: '$version'"
    }
    val base = major.toLong() * SLOT * SLOT + minor.toLong() * SLOT + patch.toLong()
    val code = base * SLOT + (rc.toIntOrNull() ?: FINAL)
    require(code <= MAX_VERSION_CODE) { "The version code of '$version' is too large" }
    return code.toInt()
}
