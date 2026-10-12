// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.contract

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject

/**
 * The JSON examples of an OpenAPI document, named as the fake server's fixtures are:
 * - `components.examples.<name>` → `<name>`;
 * - `components.responses.<Name>` → `response.<Name>` (or `response.<Name>.<example>`);
 * - an operation's inline response example → `<operationId>.<status>` (or
 *   `<operationId>.<status>.<example>`);
 * - an operation's request body example → `<operationId>.request`.
 *
 * Only JSON media types count (`application/json`, `application/problem+json`); XML strings and
 * `$ref`s to shared examples are skipped (the shared ones are extracted once, by name).
 */
internal object ContractExamples {
    private val HTTP_METHODS = setOf("get", "post", "put", "patch", "delete")

    fun extract(document: JsonObject): Map<String, JsonElement> {
        val out = sortedMapOf<String, JsonElement>()
        val components = document["components"]?.jsonObject
        components?.get("examples")?.jsonObject?.forEach { (name, example) ->
            example.jsonObject["value"]?.takeIf { it.isJson() }?.let { out[name] = it }
        }
        components?.get("responses")?.jsonObject?.forEach { (name, response) ->
            collectContent(response.jsonObject, "response.$name", out)
        }
        document["paths"]?.jsonObject?.values?.forEach { pathItem ->
            pathItem.jsonObject.filterKeys { it in HTTP_METHODS }.values.forEach { operation ->
                collectOperation(operation.jsonObject, out)
            }
        }
        return out
    }

    private fun collectOperation(operation: JsonObject, out: MutableMap<String, JsonElement>) {
        val id = (operation["operationId"] as JsonPrimitive).content
        operation["responses"]?.jsonObject?.forEach { (status, response) ->
            collectContent(response.jsonObject, "$id.$status", out)
        }
        operation["requestBody"]?.jsonObject?.let { collectContent(it, "$id.request", out) }
    }

    private fun collectContent(
        holder: JsonObject,
        name: String,
        out: MutableMap<String, JsonElement>
    ) {
        val content = holder["content"]?.jsonObject ?: return
        content.filterKeys { it.endsWith("json") }.values.forEach { media ->
            val mediaObject = media.jsonObject
            mediaObject["example"]?.takeIf { it.isJson() }?.let { out.putOnce(name, it) }
            mediaObject["examples"]?.jsonObject?.forEach { (exampleName, example) ->
                example.jsonObject["value"]?.takeIf {
                    it.isJson()
                }?.let { out.putOnce("$name.$exampleName", it) }
            }
        }
    }

    private fun MutableMap<String, JsonElement>.putOnce(name: String, value: JsonElement) {
        check(put(name, value) == null) { "Two JSON examples named '$name'" }
    }

    /** A JSON example (object or array), not an XML string or a `$ref`. */
    private fun JsonElement.isJson(): Boolean = when (this) {
        is JsonObject -> "\$ref" !in this
        is JsonPrimitive -> false
        else -> true
    }
}
