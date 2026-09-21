"""Payment saga: paid confirms + books slot; failed cancels + reopens slot; webhook idempotent."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from amrutam.api.deps import AuthUser
from amrutam.modules.payments import service as pay
from tests.helpers import book_held, make_doctor, make_patient


async def _held(
    session_factory: async_sessionmaker[AsyncSession], redis_client: object
) -> tuple[AuthUser, str, str]:
    from typing import Any

    redis: Any = redis_client
    _, slot_id = await make_doctor(session_factory)
    patient_id = await make_patient(session_factory)
    cid = await book_held(session_factory, redis, patient_id, slot_id)
    return AuthUser(id=patient_id, email="p@x.com", role="patient"), cid, slot_id


async def _statuses(
    session_factory: async_sessionmaker[AsyncSession], cid: str, slot_id: str
) -> tuple[str, str, str]:
    async with session_factory() as db:
        p = (
            await db.execute(
                text("SELECT status FROM payments WHERE consultation_id = :c"), {"c": cid}
            )
        ).scalar_one()
        c = (
            await db.execute(text("SELECT status FROM consultations WHERE id = :c"), {"c": cid})
        ).scalar_one()
        s = (
            await db.execute(
                text("SELECT status FROM availability_slots WHERE id = :s"), {"s": slot_id}
            )
        ).scalar_one()
        await db.rollback()
        return str(p), str(c), str(s)


async def test_paid_settles_confirm_and_booked(
    session_factory: async_sessionmaker[AsyncSession], redis_client: object
) -> None:
    from typing import Any

    redis: Any = redis_client
    patient, cid, slot_id = await _held(session_factory, redis)
    async with session_factory() as db:
        out = await pay.create_intent(db, redis, patient, cid, 500, "INR", False, "pay-ok-1")
        assert out["status"] == "paid"
    assert await _statuses(session_factory, cid, slot_id) == ("paid", "confirmed", "booked")


async def test_failed_compensates_cancel_and_reopen(
    session_factory: async_sessionmaker[AsyncSession], redis_client: object
) -> None:
    from typing import Any

    redis: Any = redis_client
    patient, cid, slot_id = await _held(session_factory, redis)
    async with session_factory() as db:
        out = await pay.create_intent(db, redis, patient, cid, 500, "INR", True, "pay-fail-1")
        assert out["status"] == "failed"
    assert await _statuses(session_factory, cid, slot_id) == ("failed", "cancelled", "open")


async def test_webhook_replay_identical(
    session_factory: async_sessionmaker[AsyncSession], redis_client: object
) -> None:
    from typing import Any

    redis: Any = redis_client
    patient, cid, _ = await _held(session_factory, redis)
    async with session_factory() as db:
        first = await pay.create_intent(db, redis, patient, cid, 500, "INR", False, "pay-rp-1")
    async with session_factory() as db:
        second = await pay.apply_webhook(db, cid, "paid", str(first["gateway_ref"]))
        assert second == first  # idempotent replay, no double side-effects
    async with session_factory() as db:
        with pytest.raises(Exception):  # noqa: B017, PT011
            await pay.apply_webhook(db, cid, "failed", "mock_other_ref")
