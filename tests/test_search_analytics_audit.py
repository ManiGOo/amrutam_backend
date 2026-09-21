"""Search (replica), analytics (admin-only mat views), audit chain middleware."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from amrutam.core import security
from amrutam.core.config import Settings
from amrutam.main import create_app
from amrutam.modules.analytics.service import refresh_matviews
from tests.conftest import unique_email
from tests.helpers import make_doctor


async def _make_admin(session_factory: async_sessionmaker[AsyncSession]) -> tuple[str, str]:
    email = unique_email("admin")
    async with session_factory() as db:
        uid = (
            await db.execute(
                text(
                    "INSERT INTO users (email, password_hash, role) "
                    "VALUES (:e, :p, 'admin') RETURNING id::text"
                ),
                {"e": email, "p": security.hash_password("AdminPass123")},  # noqa: S106
            )
        ).scalar_one()
        await db.execute(
            text("INSERT INTO profiles (user_id, full_name) VALUES (:u, 'Admin')"), {"u": uid}
        )
        await db.commit()
        return email, uid


def _login(client: TestClient, email: str, password: str) -> str:
    r = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_search_finds_doctor_and_analytics_admin_only(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await make_doctor(session_factory, specialization="PanchakarmaCare")
    async with session_factory() as db:
        await refresh_matviews(db)
    admin_email, _ = await _make_admin(session_factory)

    with TestClient(create_app(settings)) as client:
        # search is public, served from replica
        s = client.get("/v1/search/doctors", params={"q": "Panchakarma"})
        assert s.status_code == 200, s.text
        assert any("Panchakarma" in d["specialization"] for d in s.json())

        # analytics requires admin
        pat_email = unique_email("pat")
        client.post(
            "/v1/auth/register",
            json={
                "email": pat_email,
                "password": "StrongPass123",
                "role": "patient",
                "full_name": "Pat",
            },
        )
        pat_tok = _login(client, pat_email, "StrongPass123")
        assert client.get("/v1/analytics/funnel").status_code == 401
        denied = client.get("/v1/analytics/funnel", headers={"Authorization": f"Bearer {pat_tok}"})
        assert denied.status_code == 403

        admin_tok = _login(client, admin_email, "AdminPass123")
        ok = client.get("/v1/analytics/funnel", headers={"Authorization": f"Bearer {admin_tok}"})
        assert ok.status_code == 200, ok.text
        daily = client.get("/v1/analytics/daily", headers={"Authorization": f"Bearer {admin_tok}"})
        assert daily.status_code == 200


async def test_audit_chain_written_on_mutation(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with session_factory() as db:
        # drop pre-chain rows written before write_audit existed (dev-data hygiene)
        async with db.begin():
            await db.execute(text("DELETE FROM audit_logs WHERE hash = ''"))
        before = (await db.execute(text("SELECT count(*) FROM audit_logs"))).scalar_one()
        await db.rollback()
    with TestClient(create_app(settings)) as client:
        email = unique_email("audit")
        r = client.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": "StrongPass123",
                "role": "patient",
                "full_name": "Audit",
            },
        )
        assert r.status_code == 201, r.text
    async with session_factory() as db:
        after = (await db.execute(text("SELECT count(*) FROM audit_logs"))).scalar_one()
        assert after > before
        # register wrote its own audit row
        mine = (
            await db.execute(
                text(
                    "SELECT hash FROM audit_logs WHERE action = 'POST /v1/auth/register' "
                    "ORDER BY ts DESC LIMIT 1"
                )
            )
        ).first()
        assert mine is not None and len(mine[0]) == 64
        # linkage shape: every prev_hash references a real earlier hash (or genesis '')
        rows = (await db.execute(text("SELECT prev_hash, hash FROM audit_logs"))).all()
        await db.rollback()
        hashes = {h for _, h in rows}
        assert all(h and len(h) == 64 for h in hashes)
        assert all(p == "" or p in hashes for p, _ in rows)
