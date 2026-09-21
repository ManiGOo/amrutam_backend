"""Shared Day-3 flow helpers (register doctor/patient, slot, booking)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from amrutam.modules.auth.schemas import RegisterRequest
from amrutam.modules.auth.service import register
from amrutam.modules.bookings.service import handle_booking
from amrutam.modules.doctors.service import create_slot
from tests.conftest import unique_email


async def make_patient(
    session_factory: async_sessionmaker[AsyncSession], prefix: str = "pat"
) -> str:
    async with session_factory() as db:
        me = await register(
            db,
            RegisterRequest(
                email=unique_email(prefix),
                password="StrongPass123",  # noqa: S106
                role="patient",
                full_name=f"{prefix} Name",
            ),
        )
        return me["id"]


async def make_doctor(
    session_factory: async_sessionmaker[AsyncSession], specialization: str = "Ayurveda"
) -> tuple[str, str]:
    async with session_factory() as db:
        me = await register(
            db,
            RegisterRequest(
                email=unique_email("doc"),
                password="StrongPass123",  # noqa: S106
                role="doctor",
                full_name="Doc Tor",
                specialization=specialization,
                license_no=f"LIC-{uuid.uuid4().hex[:8]}",
            ),
        )
        start = datetime.now(UTC) + timedelta(hours=1)
        slot = await create_slot(db, me["id"], start, start + timedelta(minutes=30))
        return me["id"], str(slot["id"])


async def book_held(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Any,
    patient_id: str,
    slot_id: str,
) -> str:
    async with session_factory() as db:
        body, _ = await handle_booking(db, redis_client, patient_id, slot_id, f"t3-{uuid.uuid4()}")
        return body["id"]
