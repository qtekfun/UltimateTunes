// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.contract

import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.jsonObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.TestFactory

/**
 * The fake server's fixtures (`src/testFixtures/resources/contract-examples/<api>/<name>.json`) are
 * copies of the examples in contracts/openapi. This test fails when they drift apart: a changed,
 * added or removed example. After a contract change, regenerate the copies with
 * `./gradlew :core:api:testDebugUnitTest -PupdateContractFixtures` and review the diff.
 */
class ContractExamplesTest {
    private val contractsDir = File(requireNotNull(System.getProperty("ut.contractsDir")))
    private val fixturesDir = File(requireNotNull(System.getProperty("ut.fixturesDir")))
    private val update = System.getProperty("ut.updateContractFixtures") == "true"
    private val printer = Json { prettyPrint = true }

    @TestFactory
    fun `fixtures match the contract examples`(): List<DynamicTest> = CONTRACTS.map { (api, file) ->
        DynamicTest.dynamicTest(api) {
            val document = MiniYaml.parse(File(contractsDir, file).readText()).jsonObject
            val examples = ContractExamples.extract(document)
            assertTrue(examples.isNotEmpty(), "No JSON examples in $file")
            val dir = File(fixturesDir, api)
            if (update) write(dir, examples)
            assertEquals(examples.keys, fixtureNames(dir), "Fixture files of $api ($file)")
            examples.forEach { (name, example) ->
                val fixture = Json.parseToJsonElement(File(dir, "$name.json").readText())
                assertEquals(example, fixture, "$api/$name.json differs from its example in $file")
            }
        }
    }

    private fun fixtureNames(dir: File): Set<String> = dir.listFiles { file ->
        file.extension == "json"
    }.orEmpty().map { it.nameWithoutExtension }.toSortedSet()

    private fun write(dir: File, examples: Map<String, JsonElement>) {
        dir.mkdirs()
        dir.listFiles { file -> file.extension == "json" }.orEmpty().forEach { it.delete() }
        examples.forEach { (name, example) ->
            File(
                dir,
                "$name.json"
            ).writeText(printer.encodeToString(JsonElement.serializer(), example) + "\n")
        }
    }

    private companion object {
        val CONTRACTS = listOf(
            "opensubsonic" to "opensubsonic-subset.yaml",
            "ut-v1" to "ut-v1.yaml"
        )
    }
}
