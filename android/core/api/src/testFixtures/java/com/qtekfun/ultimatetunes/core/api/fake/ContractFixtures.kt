// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.fake

/**
 * The JSON examples of the contracts, copied to `contract-examples/<api>/<name>.json` in the test
 * fixtures and kept identical to contracts/openapi by `ContractExamplesTest`.
 *
 * Names: `<example>` for the shared OpenSubsonic examples (`getAlbum_ok`, `failed_notFound`),
 * `<operationId>.<status>[.<example>]` for inline ones (`getTrackStatus.200.ready`), and
 * `response.<Name>` for shared responses (`response.Unauthorized`).
 */
object ContractFixtures {
    const val OPENSUBSONIC = "opensubsonic"
    const val UT_V1 = "ut-v1"

    /** The fixture [name] of [api] as JSON text. */
    fun json(api: String, name: String): String {
        val path = "contract-examples/$api/$name.json"
        val stream =
            checkNotNull(ContractFixtures::class.java.classLoader?.getResourceAsStream(path)) {
                "No contract example $path"
            }
        return stream.use { it.readBytes().decodeToString() }
    }

    /** An OpenSubsonic example (a whole `subsonic-response` document). */
    fun openSubsonic(name: String): String = json(OPENSUBSONIC, name)

    /** A `/ut/v1` example. */
    fun utV1(name: String): String = json(UT_V1, name)
}
