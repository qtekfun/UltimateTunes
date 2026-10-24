# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/ut/v1/me` and `/ut/v1/keys` (contracts/openapi/ut-v1.yaml). Owner: PLAN T04.

Routes in `router` need an API key: `ut/__init__.py` authenticates it (rate limit, last use)
before the handler runs; handlers depend on the same `current_principal`, which FastAPI caches
per request, so the key is checked once. `POST /ut/v1/keys` is in `public_router`: it
authenticates with username and password (`AuthService.create_key_with_password`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from ultimatetunes.auth.repository import ApiKey
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.web import auth_service
from ultimatetunes.core.authn import Principal, current_principal
from ultimatetunes.core.forwarded import trusted_origin
from ultimatetunes.errors import InvalidParameter, PayloadTooLarge

router = APIRouter()
public_router = APIRouter()

MAX_BODY_BYTES = 16 * 1024

Service = Annotated[AuthService, Depends(auth_service)]


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# The same dependency as the router's, so FastAPI resolves the caller once per request.
Caller = Annotated[Principal, Depends(current_principal)]


def key_json(key: ApiKey, current_key_id: str | None) -> dict[str, object]:
    return {
        "id": key.id,
        "name": key.name,
        "prefix": key.prefix,
        "createdAt": key.created_at,
        "lastUsedAt": key.last_used_at,
        "revokedAt": key.revoked_at,
        "current": key.id == current_key_id,
    }


@router.get("/ut/v1/me")
def get_me(principal: Caller) -> Response:
    # `caller` always comes from an API key, so `apiKeyId` is always set.
    return JSONResponse(
        {
            "id": principal.user_id,
            "username": principal.username,
            "role": principal.role,
            "apiKeyId": principal.api_key_id,
        }
    )


@router.get("/ut/v1/keys")
def list_keys(principal: Caller, service: Service) -> Response:
    keys = service.list_keys(principal.user_id)
    return JSONResponse({"keys": [key_json(k, principal.api_key_id) for k in keys]})


class CreateKeyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=100)
    # Optional TOTP second factor (a code or a recovery code): only consulted for 2FA-enabled
    # accounts, so clients that omit it are unaffected.
    totp: SecretStr | None = Field(default=None, max_length=64)


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise PayloadTooLarge("Body over 16 KiB")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise PayloadTooLarge("Body over 16 KiB")
    return bytes(body)


@public_router.post("/ut/v1/keys")
async def create_key(request: Request, service: Service) -> Response:
    raw = await _read_body(request)
    try:
        body = CreateKeyRequest.model_validate_json(raw)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) or "body" for e in exc.errors()})
        raise InvalidParameter(f"Invalid: {', '.join(fields)}") from None
    created = await run_in_threadpool(
        service.create_key_with_password,
        body.username,
        body.password.get_secret_value(),
        body.name,
        _client_ip(request),
        request.headers.get("x-api-key") or request.query_params.get("apiKey") or None,
        trusted=trusted_origin(request),
        totp_code=body.totp.get_secret_value() if body.totp is not None else None,
    )
    return JSONResponse(
        {"key": key_json(created.key, None), "secret": created.secret},
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/ut/v1/keys/{keyId}")
def revoke_key(keyId: str, request: Request, principal: Caller, service: Service) -> Response:  # noqa: N803 - the contract's name
    service.revoke_own_key(principal, keyId, _client_ip(request))
    return Response(status_code=204)
