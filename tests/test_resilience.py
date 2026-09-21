"""Failure-injection tests: Redis down must not break correctness."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from amrutam.core.errors import RateLimited
from amrutam.core.ratelimit import check_rate_limit
from amrutam.modules.bookings.service import handle_booking
from tests.helpers import make_doctor, make_patient


class DeadRedis:
    """Every command raises like a severed connection."""

    def __getattr__(self, name: str) -> Any:
        def _dead(*args: Any, **kwargs: Any) -> Any:
            raise ConnectionError(f"redis down ({name})")

        return _dead


async def test_booking_succeeds_with_redis_down(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    patient_id = await make_patient(session_factory, "resilient")
    _, slot_id = await make_doctor(session_factory)
    dead: Any = DeadRedis()
    async with session_factory() as db:
        body, replayed = await handle_booking(db, dead, patient_id, slot_id, f"dead-{uuid.uuid4()}")
    assert replayed is False and body["status"] == "held"


async def test_idempotent_retry_with_redis_down_uses_pg_fallback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    patient_id = await make_patient(session_factory, "resilient2")
    _, slot_id = await make_doctor(session_factory)
    dead: Any = DeadRedis()
    key = f"dead-{uuid.uuid4()}"
    async with session_factory() as db:
        body1, r1 = await handle_booking(db, dead, patient_id, slot_id, key)
        assert r1 is False
    async with session_factory() as db:
        body2, r2 = await handle_booking(db, dead, patient_id, slot_id, key)
        assert r2 is True and body2 == body1
    # durable row exists even though Redis never saw it
    async with session_factory() as db:
        status = (
            await db.execute(text("SELECT status FROM idempotency_keys WHERE key = :k"), {"k": key})
        ).scalar_one()
        await db.rollback()
        assert status == "completed"


async def test_rate_limit_fails_open_with_redis_down(redis_client: Any) -> None:
    await check_rate_limit(DeadRedis(), "anyone", limit=1, window_s=60)  # must not raise
    # ...while live Redis still enforces the bucket
    await check_rate_limit(redis_client, f"strict-{uuid.uuid4()}", limit=1, window_s=60)
    try:
        await check_rate_limit(redis_client, f"strict-{uuid.uuid4()}", limit=0, window_s=60)
        raise AssertionError("expected RateLimited")
    except RateLimited:
        pass
