"""Prescriptions: sealed roundtrip, authz, signed-URL."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from amrutam.api.deps import AuthUser
from amrutam.core.config import Settings
from amrutam.core.errors import Forbidden
from amrutam.modules.consultations import service as cons
from amrutam.modules.prescriptions import service as rx
from amrutam.modules.prescriptions.pdf_store import MemoryPdfStore
from tests.helpers import book_held, make_doctor, make_patient


async def _held_with_users(
    session_factory: async_sessionmaker[AsyncSession], redis_client: object
) -> tuple[AuthUser, AuthUser, AuthUser, str]:
    from typing import Any

    redis: Any = redis_client
    doctor_id, slot_id = await make_doctor(session_factory)
    patient_id = await make_patient(session_factory)
    cid = await book_held(session_factory, redis, patient_id, slot_id)
    return (
        AuthUser(id=patient_id, email="p@x.com", role="patient"),
        AuthUser(id=doctor_id, email="d@x.com", role="doctor"),
        AuthUser(id="x", email="admin@x.com", role="admin"),
        cid,
    )


async def test_rx_roundtrip_and_pdf_url(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: object,
    settings: Settings,
) -> None:
    patient, doctor, _, cid = await _held_with_users(session_factory, redis_client)
    store = MemoryPdfStore()
    async with session_factory() as db:
        await cons.transition(db, cid, doctor, "confirm")
    async with session_factory() as db:
        created = await rx.create_prescription(
            db, store, settings, cid, doctor, "Vata imbalance", ["Ashwagandha 500mg", "Triphala"]
        )
    async with session_factory() as db:
        view = await rx.view_prescription(db, settings, created["id"], patient)
        assert view["diagnosis"] == "Vata imbalance"
        assert view["medicines"] == ["Ashwagandha 500mg", "Triphala"]
    # stored payload is ciphertext, not plaintext
    async with session_factory() as db:
        from sqlalchemy import text

        raw = (
            await db.execute(
                text("SELECT encrypted_payload FROM prescriptions WHERE id = :r"),
                {"r": created["id"]},
            )
        ).scalar_one()
        assert b"Vata" not in bytes(raw)
    async with session_factory() as db:
        url = await rx.pdf_signed_url(db, store, created["id"], patient)
        assert url["url"].startswith("memory://")
    assert store.objects[f"rx/{created['id']}.pdf"][:4] == b"%PDF"


async def test_rx_forbidden_for_stranger_and_patient_cannot_create(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: object,
    settings: Settings,
) -> None:
    patient, doctor, _, cid = await _held_with_users(session_factory, redis_client)
    store = MemoryPdfStore()
    async with session_factory() as db:
        await cons.transition(db, cid, doctor, "confirm")
    async with session_factory() as db:
        created = await rx.create_prescription(db, store, settings, cid, doctor, "Kapha", ["Tulsi"])
    stranger = AuthUser(id="stranger", email="s@x.com", role="patient")
    async with session_factory() as db:
        with pytest.raises(Forbidden):
            await rx.view_prescription(db, settings, created["id"], stranger)
    async with session_factory() as db:
        with pytest.raises(Forbidden):
            await rx.create_prescription(db, store, settings, cid, patient, "X", ["Y"])
