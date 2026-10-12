# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The OpenSubsonic pipeline: `/rest/<name>` and `/rest/<name>.view`, GET and form POST.

Each route file under `subsonic/routes/` owns its endpoints through a `SubsonicRouter`:

    router = SubsonicRouter()

    @router.endpoint("getAlbum")
    def get_album(req: SubsonicRequest) -> Payload:
        album_id = req.require("id")
        ...
        return {"album": {...}}

A handler (sync or async; sync ones run in the thread pool) returns the payload, which the
pipeline wraps in the `ok` envelope, or a Starlette `Response` (binary endpoints). It raises
`TunesError`s for failures. Before the handler, the pipeline reads the parameters (query
string, plus the `application/x-www-form-urlencoded` body of a POST, the `formPost`
extension), picks the format from `f`, checks `v`, and authenticates through
`Services.authenticator` unless the endpoint is public. Every error, expected or not, becomes
the failed envelope in the requested format.
"""

import logging
import secrets
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from inspect import iscoroutinefunction
from typing import cast
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from ultimatetunes.core.authn import Principal
from ultimatetunes.core.services import Services, services
from ultimatetunes.errors import (
    InternalError,
    InvalidParameter,
    MissingParameter,
    PayloadTooLarge,
    ServerTooOld,
    TunesError,
)
from ultimatetunes.subsonic.envelope import Format, envelope, render, render_error

log = logging.getLogger(__name__)

Payload = Mapping[str, object]
HandlerResult = Payload | Response
Handler = Callable[["SubsonicRequest"], HandlerResult | Awaitable[HandlerResult]]
FORM_TYPE = "application/x-www-form-urlencoded"
MAX_FORM_BYTES = 1024 * 1024


@dataclass
class SubsonicRequest:
    """What a handler sees: the merged parameters, the format, the caller and the services."""

    request: Request
    params: dict[str, list[str]]
    format: Format
    services: Services
    principal: Principal | None = None

    def get(self, name: str) -> str | None:
        values = self.params.get(name)
        return values[0] if values else None

    def get_all(self, name: str) -> list[str]:
        return list(self.params.get(name, ()))

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None or value == "":
            raise MissingParameter(f"Required parameter is missing: {name}")
        return value

    def get_int(self, name: str, default: int | None = None) -> int | None:
        value = self.get(name)
        if value is None or value == "":
            return default
        try:
            return int(value)
        except ValueError:
            raise InvalidParameter(f"Parameter {name} must be an integer") from None

    @property
    def user(self) -> Principal:
        """The authenticated caller (only None on public endpoints)."""
        if self.principal is None:
            raise RuntimeError("no principal on a public endpoint")
        return self.principal


@dataclass(frozen=True)
class Endpoint:
    name: str
    handler: Handler
    public: bool = False


@dataclass
class SubsonicRouter:
    endpoints: dict[str, Endpoint] = field(default_factory=dict)

    def endpoint(self, name: str, *, public: bool = False) -> Callable[[Handler], Handler]:
        def register(handler: Handler) -> Handler:
            if name in self.endpoints:
                raise ValueError(f"endpoint {name} registered twice")
            self.endpoints[name] = Endpoint(name, handler, public)
            return handler

        return register


async def read_params(request: Request) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {}
    pairs: list[tuple[str, str]] = list(request.query_params.multi_items())
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if request.method == "POST" and content_type == FORM_TYPE:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_FORM_BYTES:
                raise PayloadTooLarge("Form body too large")
        pairs.extend(parse_qsl(body.decode("utf-8", errors="replace"), keep_blank_values=True))
    for key, value in pairs:
        params.setdefault(key, []).append(value)
    return params


def response_format(params: Mapping[str, Sequence[str]]) -> Format:
    requested = (params.get("f") or ["xml"])[0]
    if requested == "json":
        return "json"
    if requested == "xml":
        return "xml"
    raise InvalidParameter(f"Unsupported format: {requested[:20]}")


def check_version(params: Mapping[str, Sequence[str]]) -> None:
    """A client speaking a newer major protocol version gets error 30."""
    version = (params.get("v") or [""])[0]
    major = version.split(".", 1)[0]
    if major.isdigit() and int(major) > 1:
        raise ServerTooOld()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _run(endpoint: Endpoint, request: Request) -> Response:
    fmt: Format = "xml"
    try:
        params = await read_params(request)
        fmt = response_format(params)
        check_version(params)
        svc = services(request)
        principal = None
        if not endpoint.public:
            principal = await run_in_threadpool(
                svc.authenticator.authenticate_subsonic, params, _client_ip(request)
            )
        ctx = SubsonicRequest(request, params, fmt, svc, principal)
        if iscoroutinefunction(endpoint.handler):
            result = await cast(
                "Callable[[SubsonicRequest], Awaitable[HandlerResult]]", endpoint.handler
            )(ctx)
        else:
            result = cast("HandlerResult", await run_in_threadpool(endpoint.handler, ctx))
    except TunesError as error:
        return render_error(error, fmt)
    except Exception:
        correlation = secrets.token_hex(4)
        log.exception("subsonic %s failed (correlation id %s)", endpoint.name, correlation)
        return render_error(InternalError(f"Internal error, correlation id {correlation}"), fmt)
    if isinstance(result, Response):
        return result
    return render(envelope(result), fmt)


def _route(endpoint: Endpoint) -> Callable[[Request], Awaitable[Response]]:
    async def route(request: Request) -> Response:
        return await _run(endpoint, request)

    return route


def build_rest_router(routers: Sequence[SubsonicRouter]) -> APIRouter:
    """One FastAPI route per endpoint and suffix; duplicate names across files are an error."""
    api = APIRouter()
    seen: dict[str, Endpoint] = {}
    for router in routers:
        for name, endpoint in router.endpoints.items():
            if name in seen:
                raise ValueError(f"endpoint {name} registered twice")
            seen[name] = endpoint
            route = _route(endpoint)
            for path in (f"/rest/{name}", f"/rest/{name}.view"):
                api.add_api_route(
                    path,
                    route,
                    methods=["GET", "POST"],
                    include_in_schema=False,
                    name=f"{name}:{path}",
                )
    return api
