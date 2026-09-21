"""Consultation lifecycle state machine + slot side-effects.

held → confirmed → in_progress → completed
held/confirmed → cancelled (releases slot back to open — saga compensation)
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.api.deps import AuthUser
from amrutam.core.audit import write_audit
from amrutam.core.errors import BadRequest, Conflict, Forbidden, NotFound

_NEXT: dict[str, dict[str, str]] = {
    "held": {"confirm": "confirmed", "cancel": "cancelled"},
    "confirmed": {"start": "in_progress", "cancel": "cancelled"},
    "in_progress": {"complete": "completed", "cancel": "cancelled"},
    "completed": {},
    "cancelled": {},
}


async def _get(db: AsyncSession, cid: str) -> Any:
    row = (
        await db.execute(
            text(
                "SELECT id::text, patient_id::text, doctor_id::text, slot_id::text, "
                "status, created_at FROM consultations WHERE id = :c"
            ),
            {"c": cid},
        )
    ).first()
    if row is None:
        raise NotFound("consultation not found")
    return row


def _authorize(row: Any, user: AuthUser) -> None:
    if user.role == "admin":
        return
    if user.role == "patient" and row[1] != user.id:
        raise Forbidden("not your consultation")
    if user.role == "doctor" and row[2] != user.id:
        raise Forbidden("not your consultation")


async def get_consultation(db: AsyncSession, cid: str, user: AuthUser) -> dict[str, Any]:
    row = await _get(db, cid)
    _authorize(row, user)
    return {
        "id": row[0],
        "patient_id": row[1],
        "doctor_id": row[2],
        "slot_id": row[3],
        "status": row[4],
        "created_at": row[5],
    }


async def list_mine(
    db: AsyncSession, user: AuthUser, limit: int = 20, cursor: str | None = None
) -> list[dict[str, Any]]:
    col = "patient_id" if user.role == "patient" else "doctor_id"
    base_cols = (
        "SELECT id::text, patient_id::text, doctor_id::text, slot_id::text,"
        " status, created_at FROM consultations"
    )
    if user.role == "admin":
        rows = (
            await db.execute(
                text(
                    "SELECT id::text, patient_id::text, doctor_id::text, slot_id::text,"
                    " status, created_at FROM consultations "
                    "ORDER BY created_at DESC LIMIT :l"
                ),
                {"l": limit},
            )
        ).all()
    elif cursor:
        if col == "patient_id":
            rows = (
                await db.execute(
                    text(
                        base_cols + " WHERE patient_id = :u AND created_at < :c "
                        "ORDER BY created_at DESC LIMIT :l"
                    ),
                    {"u": user.id, "c": cursor, "l": limit},
                )
            ).all()
        else:
            rows = (
                await db.execute(
                    text(
                        base_cols + " WHERE doctor_id = :u AND created_at < :c "
                        "ORDER BY created_at DESC LIMIT :l"
                    ),
                    {"u": user.id, "c": cursor, "l": limit},
                )
            ).all()
    elif col == "patient_id":
        rows = (
            await db.execute(
                text(base_cols + " WHERE patient_id = :u ORDER BY created_at DESC LIMIT :l"),
                {"u": user.id, "l": limit},
            )
        ).all()
    else:
        rows = (
            await db.execute(
                text(base_cols + " WHERE doctor_id = :u ORDER BY created_at DESC LIMIT :l"),
                {"u": user.id, "l": limit},
            )
        ).all()
    return [
        {
            "id": r[0],
            "patient_id": r[1],
            "doctor_id": r[2],
            "slot_id": r[3],
            "status": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]


async def transition(db: AsyncSession, cid: str, user: AuthUser, action: str) -> dict[str, Any]:
    async with db.begin():
        row = await _get(db, cid)
        _authorize(row, user)
        cur = row[4]
        nxt = _NEXT.get(cur, {}).get(action)
        if nxt is None:
            raise BadRequest(f"illegal transition {cur} + {action}")
        # Only doctor/admin drive clinical progress; patients may cancel.
        if action in ("confirm", "start", "complete") and user.role not in ("doctor", "admin"):
            raise Forbidden(f"action {action} requires doctor or admin")
        if action == "cancel" and user.role not in ("patient", "doctor", "admin"):
            raise Forbidden("cannot cancel")

        await db.execute(
            text("UPDATE consultations SET status = :s WHERE id = :c"), {"s": nxt, "c": cid}
        )
        if nxt == "cancelled":
            # compensation: release slot (idempotent — only if still held/booked)
            await db.execute(
                text(
                    "UPDATE availability_slots SET status = 'open' "
                    "WHERE id = :s AND status IN ('held', 'booked')"
                ),
                {"s": row[3]},
            )
            await db.execute(
                text(
                    "INSERT INTO outbox_events (aggregate, event, payload) "
                    "VALUES ('consultation', 'consultation.cancelled', :pl)"
                ),
                {"pl": json.dumps({"consultation_id": cid})},
            )
        elif nxt == "confirmed":
            await db.execute(
                text(
                    "UPDATE availability_slots SET status = 'booked' "
                    "WHERE id = :s AND status = 'held'"
                ),
                {"s": row[3]},
            )
            await db.execute(
                text(
                    "INSERT INTO outbox_events (aggregate, event, payload) "
                    "VALUES ('consultation', 'consultation.confirmed', :pl)"
                ),
                {"pl": json.dumps({"consultation_id": cid})},
            )
        await write_audit(
            db,
            actor=user.id,
            action=f"consultation.{action}",
            entity="consultation",
            entity_id=cid,
            payload={"from": cur, "to": nxt},
        )
    row2 = await _get(db, cid)
    # read autobegins a tx; close it so callers can begin their own
    await db.rollback()
    if row2[4] != nxt:
        raise Conflict("transition lost update")
    return {
        "id": row2[0],
        "patient_id": row2[1],
        "doctor_id": row2[2],
        "slot_id": row2[3],
        "status": row2[4],
        "created_at": row2[5],
    }
