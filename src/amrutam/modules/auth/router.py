from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.api.deps import AuthUser, get_current_user, get_redis, get_session, require_role
from amrutam.core.config import Settings, get_settings
from amrutam.core.errors import BadRequest
from amrutam.modules.auth import service
from amrutam.modules.auth.schemas import (
    LoginRequest,
    MeResponse,
    MfaEnrollResponse,
    MfaVerifyRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/register", response_model=MeResponse, status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_session)) -> MeResponse:
    user = await service.register(db, payload)
    return MeResponse(**user)


@router.post("/login", response_model=TokenPair)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_session),
    redis: Any = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TokenPair:
    tokens = await service.authenticate(db, redis, payload, settings)
    return TokenPair(**tokens)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_session),
    redis: Any = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TokenPair:
    tokens = await service.rotate_refresh(db, redis, payload.refresh_token, settings)
    return TokenPair(**tokens)


@router.post("/mfa/enroll", response_model=MfaEnrollResponse)
async def mfa_enroll(
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> MfaEnrollResponse:
    out = await service.enroll_mfa(db, user.id, user.email)
    return MfaEnrollResponse(**out)


@router.post("/mfa/verify")
async def mfa_verify(
    payload: MfaVerifyRequest,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    ok = await service.verify_mfa_code(db, user.id, payload.code)
    if not ok:
        raise BadRequest("invalid totp code")
    return {"verified": True}


@router.get("/me", response_model=MeResponse)
async def me(user: AuthUser = Depends(get_current_user)) -> MeResponse:
    return MeResponse(id=user.id, email=user.email, role=user.role)


# RBAC probe (useful for tests + interrogation demo)
@router.get("/admin/ping")
async def admin_ping(_: AuthUser = Depends(require_role("admin"))) -> dict[str, str]:
    return {"status": "admin-ok"}
