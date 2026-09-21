"""Auth flow tests (register → login → refresh rotation → MFA → RBAC)."""

from __future__ import annotations

from typing import Any

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from amrutam.core.config import Settings
from amrutam.main import create_app
from amrutam.modules.auth.schemas import LoginRequest, RegisterRequest
from amrutam.modules.auth.service import authenticate, register
from tests.conftest import unique_email


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


async def test_register_login_refresh_reuse_rejected(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Any, settings: Settings
) -> None:
    email = unique_email("patient")
    async with session_factory() as db:
        me = await register(
            db,
            RegisterRequest(
                email=email, password="StrongPass123", role="patient", full_name="Pat One"
            ),
        )
        assert me["role"] == "patient"

        tokens = await authenticate(
            db, redis_client, LoginRequest(email=email, password="StrongPass123"), settings
        )
        assert tokens["access_token"] and tokens["refresh_token"]

    # HTTP-level refresh rotation + reuse detection
    with _client(settings) as client:
        r1 = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r1.status_code == 200, r1.text
        new_pair = r1.json()
        assert new_pair["refresh_token"] != tokens["refresh_token"]

        reuse = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert reuse.status_code == 401  # rotated refresh cannot be replayed


async def test_duplicate_register_conflicts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from amrutam.core.errors import Conflict

    email = unique_email("dup")
    async with session_factory() as db:
        await register(
            db,
            RegisterRequest(email=email, password="StrongPass123", role="patient", full_name="Dup"),
        )
        try:
            await register(
                db,
                RegisterRequest(
                    email=email, password="StrongPass123", role="patient", full_name="Dup2"
                ),
            )
            raise AssertionError("expected Conflict")
        except Conflict as e:
            assert e.code == "already_exists"


async def test_mfa_enroll_verify_and_login_with_totp(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Any, settings: Settings
) -> None:
    from amrutam.modules.auth.service import enroll_mfa, verify_mfa_code

    email = unique_email("mfa")
    async with session_factory() as db:
        me = await register(
            db,
            RegisterRequest(
                email=email, password="StrongPass123", role="patient", full_name="Mfa User"
            ),
        )
        out = await enroll_mfa(db, me["id"], email)
        assert "otpauth_url" in out
        code = pyotp.TOTP(out["secret"]).now()
        assert await verify_mfa_code(db, me["id"], code) is True

        # login without totp must now fail with mfa_required
        from amrutam.core.errors import Unauthorized

        try:
            await authenticate(
                db, redis_client, LoginRequest(email=email, password="StrongPass123"), settings
            )
            raise AssertionError("expected mfa Unauthorized")
        except Unauthorized as e:
            assert e.code == "mfa_required"

        ok = await authenticate(
            db,
            redis_client,
            LoginRequest(email=email, password="StrongPass123", totp_code=code),
            settings,
        )
        assert ok["access_token"]


async def test_rbac_admin_probe_forbidden_for_patient(settings: Settings) -> None:
    with _client(settings) as client:
        email = unique_email("rbac")
        r = client.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": "StrongPass123",
                "role": "patient",
                "full_name": "Rbac",
            },
        )
        assert r.status_code == 201, r.text
        login = client.post("/v1/auth/login", json={"email": email, "password": "StrongPass123"})
        token = login.json()["access_token"]
        probe = client.get("/v1/auth/admin/ping", headers={"Authorization": f"Bearer {token}"})
        assert probe.status_code == 403
