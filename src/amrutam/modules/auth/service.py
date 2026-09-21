"""Auth use cases — orchestrates DB + Redis, no HTTP concerns."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.core import security
from amrutam.core.config import Settings
from amrutam.core.errors import BadRequest, Conflict, Unauthorized
from amrutam.modules.auth.schemas import LoginRequest, RegisterRequest


async def register(db: AsyncSession, payload: RegisterRequest) -> dict[str, str]:
    if payload.role == "doctor" and (not payload.specialization or not payload.license_no):
        raise BadRequest("specialization and license_no required for doctors")

    existing = await db.execute(text("SELECT id FROM users WHERE email = :e"), {"e": payload.email})
    if existing.first():
        raise Conflict("email already registered", code="already_exists")

    pw_hash = security.hash_password(payload.password)
    row = (
        await db.execute(
            text(
                "INSERT INTO users (email, password_hash, role) "
                "VALUES (:e, :p, :r) RETURNING id::text, email, role"
            ),
            {"e": payload.email, "p": pw_hash, "r": payload.role},
        )
    ).one()
    user_id: str = row[0]
    await db.execute(
        text("INSERT INTO profiles (user_id, full_name, phone) VALUES (:u, :n, :ph)"),
        {"u": user_id, "n": payload.full_name, "ph": payload.phone},
    )
    if payload.role == "doctor":
        await db.execute(
            text(
                "INSERT INTO doctors (user_id, specialization, license_no) " "VALUES (:u, :s, :l)"
            ),
            {"u": user_id, "s": payload.specialization, "l": payload.license_no},
        )
    await db.commit()
    return {"id": user_id, "email": row[1], "role": row[2]}


async def authenticate(
    db: AsyncSession, redis: Any, payload: LoginRequest, settings: Settings
) -> dict[str, str]:
    row = (
        await db.execute(
            text(
                "SELECT id::text, email, password_hash, role, mfa_secret, is_active "
                "FROM users WHERE email = :e AND deleted_at IS NULL"
            ),
            {"e": payload.email},
        )
    ).first()
    if row is None or not security.verify_password(row[2], payload.password):
        raise Unauthorized("invalid credentials")
    if not row[5]:
        raise Unauthorized("account disabled")
    user_id, role, mfa_secret = row[0], row[3], row[4]

    if mfa_secret:
        if not payload.totp_code or not security.verify_totp(mfa_secret, payload.totp_code):
            raise Unauthorized("mfa required or invalid", code="mfa_required")

    access = security.create_access_token(user_id, role, settings)
    refresh, jti = security.create_refresh_token(user_id, settings)
    try:
        await security.store_refresh(redis, jti, user_id, settings.jwt_refresh_ttl_days)
    except Exception as e:  # noqa: BLE001 — degraded: access works, refresh retries later
        import logging

        logging.getLogger(__name__).warning("refresh store skipped (redis down): %s", e)
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


async def rotate_refresh(
    db: AsyncSession, redis: Any, refresh_token: str, settings: Settings
) -> dict[str, str]:
    try:
        claims = security.decode_token(refresh_token, settings)
    except Exception:
        raise Unauthorized("invalid refresh token") from None
    if claims.get("type") != "refresh":
        raise Unauthorized("not a refresh token")
    jti = claims.get("jti", "")
    user_id = claims.get("sub", "")
    stored = await security.consume_refresh(redis, jti)
    if stored is None or stored != user_id:
        raise Unauthorized("refresh token reused or expired", code="refresh_reused")
    row = (await db.execute(text("SELECT role FROM users WHERE id = :u"), {"u": user_id})).first()
    if row is None:
        raise Unauthorized("user not found")
    role: str = row[0]
    access = security.create_access_token(user_id, role, settings)
    new_refresh, new_jti = security.create_refresh_token(user_id, settings)
    await security.store_refresh(redis, new_jti, user_id, settings.jwt_refresh_ttl_days)
    return {"access_token": access, "refresh_token": new_refresh, "token_type": "bearer"}


async def enroll_mfa(db: AsyncSession, user_id: str, email: str) -> dict[str, str]:
    secret = security.generate_mfa_secret()
    await db.execute(
        text("UPDATE users SET mfa_secret = :s WHERE id = :u"), {"s": secret, "u": user_id}
    )
    await db.commit()
    return {"secret": secret, "otpauth_url": security.get_otpauth_url(secret, email)}


async def verify_mfa_code(db: AsyncSession, user_id: str, code: str) -> bool:
    row = (
        await db.execute(text("SELECT mfa_secret FROM users WHERE id = :u"), {"u": user_id})
    ).first()
    if row is None or row[0] is None:
        raise BadRequest("mfa not enrolled")
    return security.verify_totp(row[0], code)
