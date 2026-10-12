# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The `subsonic-response` envelope in JSON and XML (contracts/openapi/opensubsonic-subset.yaml).

Handlers return the payload as JSON-shaped data (`{"album": {...}}`); this module wraps it in
the envelope and renders it in the format the client asked for. The XML follows the mapping
rule of the contract, so the XML examples there are exactly `to_xml` of the JSON examples:
scalars become attributes, objects child elements, arrays repeated elements, arrays of scalars
elements with text, `line.value` the text of `<line>`, and null or empty values nothing.
"""

import json
import re
from collections.abc import Mapping
from typing import Literal

from starlette.responses import Response

from ultimatetunes import __version__
from ultimatetunes.errors import RetryLater, TunesError, spec_for

Format = Literal["json", "xml"]
API_VERSION = "1.16.1"
SERVER_TYPE = "UltimateTunes"
XMLNS = "http://subsonic.org/restapi"
JSON_TYPE = "application/json"
XML_TYPE = "application/xml; charset=utf-8"

# Elements whose `value` property is their text content (lyrics lines).
_TEXT_VALUE = frozenset({"line"})
# Characters XML 1.0 cannot carry at all; dropped rather than producing a broken document.
_ILLEGAL_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def envelope(
    payload: Mapping[str, object] | None = None, *, error: TunesError | None = None
) -> dict[str, object]:
    body: dict[str, object] = {
        "status": "failed" if error is not None else "ok",
        "version": API_VERSION,
        "type": SERVER_TYPE,
        "serverVersion": __version__,
        "openSubsonic": True,
    }
    if error is not None:
        failure: dict[str, object] = {
            "code": spec_for(error).subsonic_code,
            "message": error.message,
        }
        if error.help_url:
            failure["helpUrl"] = error.help_url
        body["error"] = failure
    elif payload:
        body.update(payload)
    return {"subsonic-response": body}


def _scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return _ILLEGAL_XML.sub("", str(value))


def _attr(value: object) -> str:
    text = _scalar(value)
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _text(value: object) -> str:
    return _scalar(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _is_scalar(value: object) -> bool:
    return isinstance(value, str | int | float | bool)


def _element(name: str, value: object, depth: int, out: list[str]) -> None:
    pad = "  " * depth
    if _is_scalar(value):
        out.append(f"{pad}<{name}>{_text(value)}</{name}>")
        return
    if not isinstance(value, Mapping):
        raise TypeError(f"cannot map {type(value).__name__} to XML")
    attrs: list[str] = []
    children: list[tuple[str, object]] = []
    text: object = None
    for key, item in value.items():
        if item is None:
            continue
        if name in _TEXT_VALUE and key == "value":
            text = item
        elif _is_scalar(item):
            attrs.append(f' {key}="{_attr(item)}"')
        elif isinstance(item, list | tuple):
            children.extend((key, element) for element in item if element is not None)
        else:
            children.append((key, item))
    head = f"{pad}<{name}{''.join(attrs)}"
    if text is not None:
        out.append(f"{head}>{_text(text)}</{name}>")
    elif not children:
        out.append(f"{head}/>")
    else:
        out.append(f"{head}>")
        for key, child in children:
            _element(key, child, depth + 1, out)
        out.append(f"{pad}</{name}>")


def to_xml(document: Mapping[str, object]) -> str:
    """Renders `{"subsonic-response": {...}}` as the contract's XML."""
    root = document["subsonic-response"]
    if not isinstance(root, Mapping):
        raise TypeError("subsonic-response must be an object")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    _element("subsonic-response", {"xmlns": XMLNS, **root}, 0, lines)
    return "\n".join(lines) + "\n"


def render(document: Mapping[str, object], fmt: Format, status_code: int = 200) -> Response:
    if fmt == "json":
        body = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
        return Response(body, status_code=status_code, media_type=JSON_TYPE)
    return Response(to_xml(document), status_code=status_code, media_type=XML_TYPE)


def render_error(error: TunesError, fmt: Format) -> Response:
    """The failed envelope with the HTTP status of contracts/errors.md (200, or 404, 429, 501,
    503), plus `Retry-After` when the error carries one."""

    response = render(envelope(error=error), fmt, spec_for(error).subsonic_http_status)
    if isinstance(error, RetryLater):
        response.headers["Retry-After"] = str(error.retry_after_s)
    return response
