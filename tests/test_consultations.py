"""Consultation lifecycle: happy path, illegal transitions, authz, cancel compensation."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from amrutam.api.deps import AuthUser
from amrutam.core.errors import BadRequest, Forbidden
from amrutam.modules.consultations import service as cons
from tests.helpers import book_held, make_doctor, make_patient


async def _setup(
    session_factory: async_sessionmaker[AsyncSession], redis_client: object
) -> tuple[AuthUser, AuthUser, str, str]:
    from typing import Any

    redis: Any = redis_client
    doctor_id, slot_id = await make_doctor(session_factory)
    patient_id = await make_patient(session_factory)
    cid = await book_held(session_factory, redis, patient_id, slot_id)
    async with session_factory() as db:
        prow = (
            await db.execute(text("SELECT email FROM users WHERE id = :u"), {"u": patient_id})
        ).scalar_one()
        drow = (
            await db.execute(text("SELECT email FROM users WHERE id = :u"), {"u": doctor_id})
        ).scalar_one()
    return (
        AuthUser(id=patient_id, email=prow, role="patient"),
        AuthUser(id=doctor_id, email=drow, role="doctor"),
        cid,
        slot_id,
    )


async def test_full_lifecycle_to_completed(
    session_factory: async_sessionmaker[AsyncSession], redis_client: object
) -> None:
    patient, doctor, cid, _ = await _setup(session_factory, redis_client)
    async with session_factory() as db:
        assert (await cons.transition(db, cid, doctor, "confirm"))["status"] == "confirmed"
    async with session_factory() as db:
        assert (await cons.transition(db, cid, doctor, "start"))["status"] == "in_progress"
    async with session_factory() as db:
        out = await cons.transition(db, cid, doctor, "complete")
        assert out["status"] == "completed"
    async with session_factory() as db:
        with pytest.raises(BadRequest):
            await cons.transition(db, cid, doctor, "cancel")  # terminal


async def test_patient_cannot_confirm_but_can_cancel_and_slot_reopens(
    session_factory: async_sessionmaker[AsyncSession], redis_client: object
) -> None:
    patient, _, cid, slot_id = await _setup(session_factory, redis_client)
    async with session_factory() as db:
        with pytest.raises(Forbidden):
            await cons.transition(db, cid, patient, "confirm")
    async with session_factory() as db:
        out = await cons.transition(db, cid, patient, "cancel")
        assert out["status"] == "cancelled"
    async with session_factory() as db:
        status = (
            await db.execute(
                text("SELECT status FROM availability_slots WHERE id = :s"), {"s": slot_id}
            )
        ).scalar_one()
        assert status == "open"  # compensation released the hold


async def test_cross_patient_forbidden(
    session_factory: async_sessionmaker[AsyncSession], redis_client: object
) -> None:
    _, _, cid, _ = await _setup(session_factory, redis_client)
    other_id = await make_patient(session_factory, "other")
    other = AuthUser(id=other_id, email="other@x.com", role="patient")
    async with session_factory() as db:
        with pytest.raises(Forbidden):
            await cons.get_consultation(db, cid, other)
