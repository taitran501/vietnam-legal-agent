"""Authenticated identity endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.api.principal import principal_from_request_state

router = APIRouter()


@router.get("/me", tags=["identity"])
async def me(request: Request) -> dict[str, object]:
    principal = principal_from_request_state(request)
    return {
        "principal_type": principal.type,
        "principal_id": principal.id,
        "display_name": principal.display_name,
        "email": principal.email,
        "roles": sorted(principal.roles),
        "scopes": sorted(principal.scopes),
    }
