"""Booking tests: happy path, idempotent replay, single-winner race, outbox exactly-once."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from amrutam.core.config import Settings
from amrutam.core.errors import Conflict
from amrutam.modules.auth.schemas import RegisterRequest
from amrutam.modules.auth.service import register
from amrutam.modules.bookings.service import handle_booking
from amrutam.modules.doctors.service import create_slot
from amrutam.workers.relay import relay_once
from tests.conftest import unique_email


async def _make_patient(
    session_factory: async_sessionmaker[AsyncSession], prefix: str = "pat"
) -> str:
    async with session_factory() as db:
        me = await register(
            db,
            RegisterRequest(
                email=unique_email(prefix),
                password="StrongPass123",
                role="patient",
                full_name=f"{prefix} Name",
            ),
        )
        return me["id"]


async def _make_doctor_with_slot(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[str, str]:
    async with session_factory() as db:
        me = await register(
            db,
            RegisterRequest(
                email=unique_email("doc"),
                password="StrongPass123",
                role="doctor",
                full_name="Doc Tor",
                specialization="Ayurveda",
                license_no=f"LIC-{uuid.uuid4().hex[:8]}",
            ),
        )
        start = datetime.now(UTC) + timedelta(hours=1)
        end = start + timedelta(minutes=30)
        slot = await create_slot(db, me["id"], start, end)
        return me["id"], str(slot["id"])


async def test_booking_happy_path_and_replay_identical(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Any
) -> None:
    patient_id = await _make_patient(session_factory)
    _, slot_id = await _make_doctor_with_slot(session_factory)
    key = f"test-{uuid.uuid4()}"

    async with session_factory() as db:
        body1, replayed1 = await handle_booking(db, redis_client, patient_id, slot_id, key)
    assert replayed1 is False
    assert body1["status"] == "held" and body1["slot_id"] == slot_id

    async with session_factory() as db:
        body2, replayed2 = await handle_booking(db, redis_client, patient_id, slot_id, key)
    assert replayed2 is True
    assert body2 == body1  # verbatim replay, no second slot hold


async def test_second_patient_same_slot_gets_409(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Any
) -> None:
    p1 = await _make_patient(session_factory, "p1")
    p2 = await _make_patient(session_factory, "p2")
    _, slot_id = await _make_doctor_with_slot(session_factory)

    async with session_factory() as db:
        await handle_booking(db, redis_client, p1, slot_id, f"test-{uuid.uuid4()}")
    async with session_factory() as db:
        with pytest.raises(Conflict):
            await handle_booking(db, redis_client, p2, slot_id, f"test-{uuid.uuid4()}")


async def test_booking_race_ten_parallel_one_winner(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Any
) -> None:
    _, slot_id = await _make_doctor_with_slot(session_factory)
    patient_ids = [await _make_patient(session_factory, f"racer{i}") for i in range(10)]

    async def _attempt(pid: str) -> bool:
        async with session_factory() as db:
            try:
                await handle_booking(db, redis_client, pid, slot_id, f"race-{uuid.uuid4()}")
                return True
            except Conflict:
                return False

    results = await asyncio.gather(*[_attempt(pid) for pid in patient_ids])
    assert sum(results) == 1  # exactly one winner, nine 409s


async def test_outbox_emitted_exactly_once_and_relay_marks_processed(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Any,
    settings: Settings,
) -> None:
    from amrutam.core.container import Container

    patient_id = await _make_patient(session_factory, "outbox")
    _, slot_id = await _make_doctor_with_slot(session_factory)

    async with session_factory() as db:
        body, _ = await handle_booking(
            db, redis_client, patient_id, slot_id, f"test-{uuid.uuid4()}"
        )
    cid = body["id"]

    async with session_factory() as db:
        n = (
            await db.execute(
                text(
                    "SELECT count(*) FROM outbox_events WHERE event = 'booking.created' "
                    "AND payload->>'consultation_id' = :c"
                ),
                {"c": cid},
            )
        ).scalar_one()
        assert n == 1

    container = Container(settings)
    try:
        # drain until OUR event is processed (relay is oldest-first, batched;
        # load runs may leave a backlog — bounded loop keeps the test honest)
        for _ in range(20):
            await relay_once(container)
            async with session_factory() as db:
                left = (
                    await db.execute(
                        text(
                            "SELECT count(*) FROM outbox_events WHERE event = 'booking.created' "
                            "AND payload->>'consultation_id' = :c AND processed = FALSE"
                        ),
                        {"c": cid},
                    )
                ).scalar_one()
                await db.rollback()
                if left == 0:
                    break
        assert left == 0
    finally:
        await container.close()

    # stream received the event (best-effort XADD + relay XADD)
    msgs = await redis_client.xrevrange("streams:events", count=5)
    assert len(msgs) >= 1
    _ = json.dumps(msgs)  # serializable
