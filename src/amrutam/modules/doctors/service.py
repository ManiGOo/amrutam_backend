from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.core.errors import BadRequest


async def list_doctors(
    db: AsyncSession, specialization: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    if specialization:
        rows = (
            await db.execute(
                text(
                    "SELECT d.user_id::text, p.full_name, d.specialization "
                    "FROM doctors d LEFT JOIN profiles p ON p.user_id = d.user_id "
                    "WHERE d.specialization ILIKE :s LIMIT :l"
                ),
                {"s": f"%{specialization}%", "l": limit},
            )
        ).all()
    else:
        rows = (
            await db.execute(
                text(
                    "SELECT d.user_id::text, p.full_name, d.specialization "
                    "FROM doctors d LEFT JOIN profiles p ON p.user_id = d.user_id "
                    "LIMIT :l"
                ),
                {"l": limit},
            )
        ).all()
    return [{"id": r[0], "full_name": r[1], "specialization": r[2]} for r in rows]


async def create_slot(
    db: AsyncSession, doctor_id: str, starts_at: datetime, ends_at: datetime
) -> dict[str, Any]:
    if ends_at <= starts_at:
        raise BadRequest("ends_at must be after starts_at")
    if ends_at <= starts_at:
        raise BadRequest("ends_at must be after starts_at")
    row = (
        await db.execute(
            text(
                "INSERT INTO availability_slots (doctor_id, starts_at, ends_at) "
                "VALUES (:d, :s, :e) "
                "RETURNING id::text, doctor_id::text, starts_at, ends_at, status, version"
            ),
            {"d": doctor_id, "s": starts_at, "e": ends_at},
        )
    ).one()
    await db.commit()
    return {
        "id": row[0],
        "doctor_id": row[1],
        "starts_at": row[2],
        "ends_at": row[3],
        "status": row[4],
        "version": row[5],
    }


async def list_slots(
    db: AsyncSession, doctor_id: str, status: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    if status:
        rows = (
            await db.execute(
                text(
                    "SELECT id::text, doctor_id::text, starts_at, ends_at, status, version "
                    "FROM availability_slots WHERE doctor_id = :d AND status = :s "
                    "ORDER BY starts_at LIMIT :l"
                ),
                {"d": doctor_id, "s": status, "l": limit},
            )
        ).all()
    else:
        rows = (
            await db.execute(
                text(
                    "SELECT id::text, doctor_id::text, starts_at, ends_at, status, version "
                    "FROM availability_slots WHERE doctor_id = :d "
                    "ORDER BY starts_at LIMIT :l"
                ),
                {"d": doctor_id, "l": limit},
            )
        ).all()
    return [
        {
            "id": r[0],
            "doctor_id": r[1],
            "starts_at": r[2],
            "ends_at": r[3],
            "status": r[4],
            "version": r[5],
        }
        for r in rows
    ]
