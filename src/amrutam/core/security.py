"""Auth primitives: argon2id, RS256 JWT, refresh rotation (Redis), TOTP."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from amrutam.core.config import Settings, get_settings

_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


# --- RSA keys (file or ephemeral for dev/test) ---
_ephemeral_private: str | None = None
_ephemeral_public: str | None = None


def _generate_ephemeral() -> tuple[str, str]:
    global _ephemeral_private, _ephemeral_public
    if _ephemeral_private is not None and _ephemeral_public is not None:
        return _ephemeral_private, _ephemeral_public
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    _ephemeral_private, _ephemeral_public = priv, pub
    return priv, pub


@lru_cache(maxsize=1)
def _load_keys(private_path: str = "", public_path: str = "") -> tuple[str, str]:
    settings = get_settings()
    priv_path = Path(private_path or settings.jwt_private_key_path)
    pub_path = Path(public_path or settings.jwt_public_key_path)
    try:
        if priv_path.exists() and pub_path.exists():
            return priv_path.read_text(), pub_path.read_text()
    except OSError:
        pass
    return _generate_ephemeral()


def create_access_token(user_id: str, role: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    priv, _ = _load_keys()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_ttl_min),
    }
    return jwt.encode(payload, priv, algorithm="RS256", headers={"kid": settings.jwt_kid})


def create_refresh_token(user_id: str, settings: Settings | None = None) -> tuple[str, str]:
    """Returns (token, jti). Caller must store jti in Redis."""
    settings = settings or get_settings()
    priv, _ = _load_keys()
    now = datetime.now(UTC)
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(days=settings.jwt_refresh_ttl_days),
    }
    token = jwt.encode(payload, priv, algorithm="RS256", headers={"kid": settings.jwt_kid})
    return token, jti


def decode_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    _, pub = _load_keys()
    return jwt.decode(token, pub, algorithms=["RS256"], options={"require": ["exp", "sub"]})


# --- refresh rotation helpers (Redis) ---
async def store_refresh(redis: Any, jti: str, user_id: str, ttl_days: int = 7) -> None:
    await redis.set(f"refresh:{jti}", user_id, ex=ttl_days * 86400)


async def consume_refresh(redis: Any, jti: str) -> str | None:
    """GETDEL — returns user_id if valid, None if already used/missing (replay)."""
    val = await redis.getdel(f"refresh:{jti}")
    if isinstance(val, bytes):
        return val.decode()
    return val  # type: ignore[no-any-return]


# --- TOTP MFA (RFC 6238) ---
def generate_mfa_secret() -> str:
    return pyotp.random_base32()


def get_otpauth_url(secret: str, email: str, issuer: str = "Amrutam") -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception:
        return False
