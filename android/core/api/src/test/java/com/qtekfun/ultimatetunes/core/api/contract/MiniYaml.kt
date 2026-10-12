// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.contract

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * A reader for the block-style YAML subset the hand-maintained contracts use (contracts/openapi):
 * mappings, sequences (also indentless and `- key: value`), plain, single- and double-quoted
 * scalars (multi-line too), literal block scalars (`|`, `|-`, `|+`), empty or simple flow
 * collections (`[]`, `{}`, `[a, b]`) and comments. Anchors, aliases, tags, folded scalars and
 * complex keys are rejected, not misread.
 *
 * Only for tests (the fixture drift check): no YAML library is an approved dependency, and the
 * contracts are regular enough for this. A line-based parser reads best with early returns and
 * loops that skip or stop on a line, hence the suppressions.
 */
@Suppress("ReturnCount", "LoopWithTooManyJumpStatements", "CyclomaticComplexMethod")
internal class MiniYaml private constructor(text: String) {
    private val lines: MutableList<String> = text.replace("\r\n", "\n").split("\n").toMutableList()
    private var pos = 0

    companion object {
        fun parse(text: String): JsonElement {
            val reader = MiniYaml(text)
            val root = reader.parseNode(0) ?: JsonNull
            reader.skipInsignificant()
            check(reader.pos >= reader.lines.size) {
                "Unexpected content at line ${reader.pos + 1}"
            }
            return root
        }

        private val INT = Regex("^[-+]?[0-9]+$")
        private val FLOAT =
            Regex(
                "^[-+]?([0-9]+\\.[0-9]*|\\.[0-9]+)([eE][-+]?[0-9]+)?$|^[-+]?[0-9]+[eE][-+]?[0-9]+$"
            )
        private const val HEX_RADIX = 16
    }

    // ---- lines ----

    private fun indentOf(line: String): Int = line.length - line.trimStart(' ').length

    private fun isInsignificant(line: String): Boolean {
        val trimmed = line.trim()
        return trimmed.isEmpty() || trimmed.startsWith("#")
    }

    private fun skipInsignificant() {
        while (pos < lines.size && isInsignificant(lines[pos])) pos++
    }

    /** Index of the next significant line, without consuming anything. */
    private fun peek(): Int? {
        var i = pos
        while (i < lines.size && isInsignificant(lines[i])) i++
        return if (i < lines.size) i else null
    }

    private fun isSequenceItem(content: String): Boolean =
        content == "-" || content.startsWith("- ")

    // ---- nodes ----

    /** The node starting at the next significant line, if it is indented at least [minIndent]. */
    private fun parseNode(minIndent: Int): JsonElement? {
        val index = peek() ?: return null
        val line = lines[index]
        val indent = indentOf(line)
        if (indent < minIndent) return null
        val content = line.substring(indent)
        pos = index
        return when {
            isSequenceItem(content) -> parseSequence(indent)

            keyOf(content) != null -> parseMapping(indent)

            else -> {
                pos++
                parseScalarValue(content, indent - 1)
            }
        }
    }

    private fun parseMapping(indent: Int): JsonObject {
        val map = LinkedHashMap<String, JsonElement>()
        while (true) {
            val index = peek() ?: break
            val line = lines[index]
            if (indentOf(line) != indent) {
                check(indentOf(line) < indent) { "Bad indentation at line ${index + 1}" }
                break
            }
            val content = line.substring(indent)
            if (isSequenceItem(content)) break
            val (key, rest) = keyOf(content) ?: error("Expected a key at line ${index + 1}")
            check(key !in map) { "Duplicate key '$key' at line ${index + 1}" }
            pos = index + 1
            map[key] = parseValue(rest, indent)
        }
        return JsonObject(map)
    }

    private fun parseSequence(indent: Int): JsonArray {
        val items = mutableListOf<JsonElement>()
        while (true) {
            val index = peek() ?: break
            val line = lines[index]
            if (indentOf(line) != indent || !isSequenceItem(line.substring(indent))) break
            val content = line.substring(indent + 1).trimStart(' ')
            val itemIndent = line.length - content.length
            when {
                content.isEmpty() || content.startsWith("#") -> {
                    pos = index + 1
                    items += parseNode(indent + 1) ?: JsonNull
                }

                keyOf(content) != null && !content.startsWith("[") && !content.startsWith("{") -> {
                    // `- key: value`: a mapping whose keys sit at the column after "- ".
                    pos = index
                    items += parseMappingFromItem(index, itemIndent)
                }

                else -> {
                    pos = index + 1
                    items += parseScalarValue(content, indent)
                }
            }
        }
        return JsonArray(items)
    }

    /** A mapping whose first key shares the line of a `- ` sequence marker. */
    private fun parseMappingFromItem(index: Int, keyIndent: Int): JsonObject {
        val original = lines[index]
        lines[index] = " ".repeat(keyIndent) + original.substring(keyIndent)
        return try {
            parseMapping(keyIndent)
        } finally {
            lines[index] = original
        }
    }

    /** The value after `key:` on a line of indent [indent]: inline, a block scalar, or a child node. */
    private fun parseValue(rest: String, indent: Int): JsonElement {
        val value = stripComment(rest).trim()
        return when {
            value.isEmpty() -> {
                val next = peek()
                when {
                    next == null -> JsonNull

                    indentOf(lines[next]) > indent -> parseNode(indent + 1) ?: JsonNull

                    indentOf(
                        lines[next]
                    ) == indent && isSequenceItem(lines[next].substring(indent)) ->
                        parseSequence(indent)

                    else -> JsonNull
                }
            }

            else -> parseScalarValue(rest.trim(), indent)
        }
    }

    /** An inline value (already consumed line) that may continue on more-indented lines. */
    private fun parseScalarValue(text: String, indent: Int): JsonElement {
        val value = text.trim()
        check(value.firstOrNull() !in setOf('&', '*', '!', '?', '>', '%', '@', '`')) {
            "Unsupported YAML at line $pos: '$value'"
        }
        return when {
            value.startsWith("|") -> JsonPrimitive(parseLiteral(value, indent))
            value.startsWith("'") -> JsonPrimitive(parseQuoted(value, '\''))
            value.startsWith("\"") -> JsonPrimitive(parseQuoted(value, '"'))
            value.startsWith("[") || value.startsWith("{") -> parseFlow(stripComment(value).trim())
            else -> resolvePlain(parsePlain(stripComment(value).trim(), indent))
        }
    }

    // ---- scalars ----

    private fun parsePlain(first: String, indent: Int): String {
        val parts = StringBuilder(first)
        var pendingBreaks = 0
        while (pos < lines.size) {
            val line = lines[pos]
            if (line.isBlank()) {
                pendingBreaks++
                pos++
                continue
            }
            if (indentOf(line) <= indent || line.trimStart().startsWith("#")) break
            parts.append(if (pendingBreaks > 0) "\n".repeat(pendingBreaks) else " ")
            parts.append(stripComment(line).trim())
            pendingBreaks = 0
            pos++
        }
        if (pendingBreaks > 0) pos -= pendingBreaks
        return parts.toString()
    }

    private fun parseQuoted(first: String, quote: Char): String {
        val raw = StringBuilder(first.substring(1))
        // Gather lines until the closing quote.
        while (closingQuoteIndex(raw, quote) < 0) {
            check(pos < lines.size) { "Unterminated quoted scalar" }
            raw.append('\n').append(lines[pos])
            pos++
        }
        val end = closingQuoteIndex(raw, quote)
        val trailing = stripComment(raw.substring(end + 1)).trim()
        check(trailing.isEmpty() || trailing == ":") { "Text after a quoted scalar: '$trailing'" }
        val body = fold(raw.substring(0, end), escapedNewlines = quote == '"')
        return if (quote == '\'') body.replace("''", "'") else unescape(body)
    }

    private fun closingQuoteIndex(text: CharSequence, quote: Char): Int {
        var i = 0
        while (i < text.length) {
            val c = text[i]
            if (quote == '"' && c == '\\') {
                i += 2
                continue
            }
            if (c == quote) {
                if (quote == '\'' && i + 1 < text.length && text[i + 1] == '\'') {
                    i += 2
                    continue
                }
                return i
            }
            i++
        }
        return -1
    }

    /** Line folding of flow scalars: one break becomes a space, n breaks become n-1 newlines. */
    private fun fold(text: String, escapedNewlines: Boolean): String {
        val segments = text.split("\n")
        if (segments.size == 1) return text
        val out = StringBuilder(segments.first().trimEnd())
        var breaks = 0
        for (segment in segments.drop(1)) {
            val trimmed = segment.trim()
            if (trimmed.isEmpty()) {
                breaks++
                continue
            }
            when {
                escapedNewlines && out.endsWith("\\") -> out.setLength(out.length - 1)
                breaks > 0 -> out.append("\n".repeat(breaks))
                else -> out.append(' ')
            }
            out.append(trimmed)
            breaks = 0
        }
        if (breaks > 0) out.append("\n".repeat(breaks))
        return out.toString()
    }

    private fun unescape(text: String): String {
        val out = StringBuilder()
        var i = 0
        while (i < text.length) {
            val c = text[i]
            if (c != '\\') {
                out.append(c)
                i++
                continue
            }
            val next = text[i + 1]
            when (next) {
                'n' -> out.append('\n')

                't' -> out.append('\t')

                '"' -> out.append('"')

                '\\' -> out.append('\\')

                '/' -> out.append('/')

                '0' -> out.append('\u0000')

                'u' -> {
                    out.append(text.substring(i + 2, i + 6).toInt(HEX_RADIX).toChar())
                    i += 4
                }

                else -> error("Unsupported escape \\$next")
            }
            i += 2
        }
        return out.toString()
    }

    private fun parseLiteral(header: String, indent: Int): String {
        val chomping = header.removePrefix("|").trim()
        check(chomping in setOf("", "-", "+")) { "Unsupported block scalar header '$header'" }
        val body = mutableListOf<String>()
        var blockIndent = -1
        while (pos < lines.size) {
            val line = lines[pos]
            if (line.isBlank()) {
                body += ""
                pos++
                continue
            }
            val lineIndent = indentOf(line)
            if (lineIndent <= indent) break
            if (blockIndent < 0) blockIndent = lineIndent
            if (lineIndent < blockIndent) break
            body += line.substring(blockIndent)
            pos++
        }
        // Trailing blank lines belong to the chomping, not to the next node.
        var trailingBlank = 0
        while (body.isNotEmpty() && body.last().isEmpty()) {
            body.removeAt(body.size - 1)
            trailingBlank++
        }
        val text = body.joinToString("\n")
        return when (chomping) {
            "-" -> text
            "+" -> text + "\n" + "\n".repeat(trailingBlank)
            else -> if (text.isEmpty()) "" else text + "\n"
        }
    }

    private fun parseFlow(text: String): JsonElement = when {
        text == "[]" -> JsonArray(emptyList())

        text == "{}" -> JsonObject(emptyMap())

        text.startsWith("[") && text.endsWith("]") -> {
            val inner = text.substring(1, text.length - 1)
            check('[' !in inner && '{' !in inner && '\'' !in inner && '"' !in inner) {
                "Unsupported flow collection '$text'"
            }
            JsonArray(inner.split(',').map { resolvePlain(it.trim()) })
        }

        else -> error("Unsupported flow collection '$text'")
    }

    private fun resolvePlain(text: String): JsonElement = when {
        text == "null" || text == "Null" || text == "NULL" || text == "~" -> JsonNull
        text == "true" || text == "True" || text == "TRUE" -> JsonPrimitive(true)
        text == "false" || text == "False" || text == "FALSE" -> JsonPrimitive(false)
        INT.matches(text) -> JsonPrimitive(text.toLong())
        FLOAT.matches(text) -> JsonPrimitive(text.toDouble())
        else -> JsonPrimitive(text)
    }

    // ---- keys and comments ----

    /** `key: rest` of a mapping line, or null when the line is not a key. */
    private fun keyOf(content: String): Pair<String, String>? {
        if (content.startsWith("'") || content.startsWith("\"")) {
            val quote = content[0]
            val end = closingQuoteIndex(content.substring(1), quote)
            if (end < 0) return null
            val after = content.substring(end + 2)
            if (after != ":" && !after.startsWith(": ")) return null
            val raw = content.substring(1, end + 1)
            val key = if (quote == '\'') raw.replace("''", "'") else unescape(raw)
            return key to after.removePrefix(":")
        }
        if (content.startsWith("#") || content.startsWith("[") ||
            content.startsWith("{")
        ) {
            return null
        }
        val colon = Regex(":( |$)").find(content) ?: return null
        val hash = Regex("(^| )#").find(content)
        if (hash != null && hash.range.first < colon.range.first) return null
        return content.substring(0, colon.range.first) to content.substring(colon.range.first + 1)
    }

    /** [text] without a trailing ` # comment` (outside quotes). */
    private fun stripComment(text: String): String {
        var quote: Char? = null
        for (i in text.indices) {
            val c = text[i]
            when {
                quote != null -> if (c == quote) quote = null
                c == '\'' || c == '"' -> if (i == 0 || text[i - 1] == ' ') quote = c
                c == '#' && (i == 0 || text[i - 1] == ' ') -> return text.substring(0, i)
            }
        }
        return text
    }
}
