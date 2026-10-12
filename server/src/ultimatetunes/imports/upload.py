# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a `POST /ut/v1/imports` body within its limits.

The body is read in chunks and the read stops as soon as it passes the cap (a declared
`Content-Length` over the cap is refused before reading), so an upload never costs more than
`MAX_BODY_BYTES` of memory. A multipart body is then parsed from those bytes with Starlette's
parser (python-multipart), one file and a few short fields at most; the file itself must be at
most `files.MAX_FILE_BYTES`. A JSON body is small (`MAX_JSON_BYTES`).
"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass

from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import Request

from ultimatetunes.errors import InvalidParameter, PayloadTooLarge
from ultimatetunes.imports.files import FILE_FORMATS, MAX_FILE_BYTES, MAX_NAME_CHARS, FileFormat

# Room for the multipart envelope (boundaries, part headers, the short fields).
MAX_BODY_BYTES = MAX_FILE_BYTES + 64 * 1024
MAX_JSON_BYTES = 16 * 1024
_MAX_FIELD_BYTES = 4096


@dataclass(frozen=True)
class FileUpload:
    data: bytes
    fmt: FileFormat
    filename: str | None
    name: str | None


async def read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise PayloadTooLarge("The request body is too large")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise PayloadTooLarge("The request body is too large")
    return bytes(body)


async def _once(body: bytes) -> AsyncGenerator[bytes]:
    yield body


def _field(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidParameter(f"`{name}` must be a text field")
    return value.strip() or None


async def read_file_upload(request: Request) -> FileUpload:
    body = await read_body(request, MAX_BODY_BYTES)
    parser = MultiPartParser(
        request.headers, _once(body), max_files=1, max_fields=4, max_part_size=_MAX_FIELD_BYTES
    )
    try:
        form = await parser.parse()
    except MultiPartException as exc:
        raise InvalidParameter(f"Unreadable multipart body: {exc.message}") from None
    try:
        fmt = _field(form.get("format"), "format")
        if fmt not in FILE_FORMATS:
            raise InvalidParameter(f"`format` must be one of {', '.join(FILE_FORMATS)}")
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise InvalidParameter("`file` is required")
        name = _field(form.get("name"), "name")
        if name is not None and len(name) > MAX_NAME_CHARS:
            raise InvalidParameter("`name` is longer than 200 characters")
        data = await upload.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise PayloadTooLarge("The file is larger than 1 MiB")
        return FileUpload(data, fmt, upload.filename, name)
    finally:
        await form.close()
