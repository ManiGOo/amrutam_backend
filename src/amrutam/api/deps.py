from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.core import security
from amrutam.core.config import get_settings
from amrutam.core.container import Container
from amrutam.core.errors import Forbidden, Unauthorized

_bearer = HTTPBearer(auto_error=False)

_container: Container | None = None


def get_container() -> Container:
    global _container
    if _container is None:
        _container = Container(get_settings())
    return _container


def reset_container() -> None:
    """Test hook: drop the cached container so the next request builds engines
    on the current event loop (engines are loop-bound via asyncpg pools)."""
    global _container
    _container = None


async def get_session():  # type: ignore[no-untyped-def]
    async with get_container().session() as s:
        yield s


async def get_redis():  # type: ignore[no-untyped-def]
    yield await get_container().get_redis()


async def get_replica_session():  # type: ignore[no-untyped-def]
    async with get_container().replica_session() as s:
        yield s


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str
    role: str


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_session),
) -> AuthUser:
    if creds is None or not creds.credentials:
        raise Unauthorized("missing bearer token")
    try:
        claims = security.decode_token(creds.credentials)
    except Exception:
        raise Unauthorized("invalid token") from None
    if claims.get("type") != "access":
        raise Unauthorized("not an access token")
    user_id = str(claims.get("sub", ""))
    row = (
        await db.execute(
            text(
                "SELECT id::text, email, role FROM users "
                "WHERE id = :u AND deleted_at IS NULL AND is_active = TRUE"
            ),
            {"u": user_id},
        )
    ).first()
    if row is None:
        raise Unauthorized("user not found or disabled")
    # FastAPI caches generator dependencies per request, so this SELECT shares
    # its session/tx with the route handler. Roll back the read-only tx so the
    # handler can open its own unit of work (async with db.begin()).
    await db.rollback()
    return AuthUser(id=row[0], email=row[1], role=row[2])


def require_role(*roles: str):  # type: ignore[no-untyped-def]
    async def _check(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.role not in roles:
            raise Forbidden(f"requires role {roles}")
        return user

    return _check


__all__ = [
    "get_container",
    "reset_container",
    "get_session",
    "get_replica_session",
    "get_redis",
    "get_current_user",
    "require_role",
    "AuthUser",
    "Depends",
]
