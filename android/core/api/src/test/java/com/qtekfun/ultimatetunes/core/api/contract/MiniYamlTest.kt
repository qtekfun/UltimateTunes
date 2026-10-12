// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.contract

import kotlinx.serialization.json.Json
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test

/**
 * The YAML subset reader behind the fixture drift check. It was also compared against PyYAML on
 * the three contract files when written (identical results).
 */
class MiniYamlTest {
    private fun yaml(text: String) = MiniYaml.parse(text.trimIndent())

    private fun json(text: String) = Json.parseToJsonElement(text)

    @Test
    fun `mappings, sequences and scalar types`() {
        val parsed = yaml(
            """
            # comment
            a: 1
            b: -7.12
            c: 1.16.1
            d: true
            e: null
            f: '0.1.0'
            g: "x\ty"
            h: plain text # trailing comment
            i: []
            j: {}
            k: [a, 2]
            l:
            - x
            - y: 1
              z: 2
            -
              w: 3
            'quoted key': 'it''s'
            """
        )
        val expected = json(
            """
            {"a":1,"b":-7.12,"c":"1.16.1","d":true,"e":null,"f":"0.1.0","g":"x\ty","h":"plain text",
             "i":[],"j":{},"k":["a",2],"l":["x",{"y":1,"z":2},{"w":3}],"quoted key":"it's"}
            """
        )
        assertEquals(expected, parsed)
    }

    @Test
    fun `multi-line scalars fold and literal blocks keep lines`() {
        val parsed = yaml(
            """
            plain: first
              second

              third
            single: 'one
              two'
            double: "a\
              b"
            keep: |
              line 1
                indented
              line 3
            strip: |-
              only
            next: end
            """
        )
        val expected = json(
            """
            {"plain":"first second\nthird","single":"one two","double":"ab",
             "keep":"line 1\n  indented\nline 3\n","strip":"only","next":"end"}
            """
        )
        assertEquals(expected, parsed)
    }

    @Test
    fun `unsupported features are rejected, not misread`() {
        listOf(
            "a: &anchor 1",
            "a: *alias",
            "a: !!str 1",
            "a: >\n  folded",
            "a: [x, [y]]"
        ).forEach { text ->
            assertThrows(IllegalStateException::class.java, { MiniYaml.parse(text) }, text)
        }
        assertThrows(IllegalStateException::class.java) { MiniYaml.parse("a: 1\na: 2") }
    }
}
