// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.buildlogic

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.CsvSource
import org.junit.jupiter.params.provider.ValueSource

class VersionCodeTest {
    @ParameterizedTest
    @CsvSource(
        "1.0.0-rc.1, 1000001",
        "1.0.0-rc.98, 1000098",
        "1.0.0, 1000099",
        "0.0.0, 99",
        "0.1.2, 10299",
        "2.3.4-rc.5, 2030405"
    )
    fun `follows the formula of tools-version-code-sh`(version: String, expected: Int) {
        assertEquals(expected, versionCodeOf(version))
    }

    @Test
    fun `a final release sorts after its release candidates and before the next version`() {
        assertTrue(versionCodeOf("1.0.0-rc.98") < versionCodeOf("1.0.0"))
        assertTrue(versionCodeOf("1.0.0") < versionCodeOf("1.0.1-rc.1"))
    }

    @ParameterizedTest
    @ValueSource(
        strings = [
            "",
            "1.0",
            "v1.0.0",
            "1.0.0-beta.1",
            "1.0.0-rc.0",
            "1.0.0-rc.99",
            "1.100.0",
            "1.0.100",
            "1.0.0\n",
            "2200.0.0"
        ]
    )
    fun `refuses an invalid version`(version: String) {
        assertThrows<IllegalArgumentException> { versionCodeOf(version) }
    }
}
