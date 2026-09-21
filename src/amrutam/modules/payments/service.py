"""Payment saga: intent → mock charge → webhook settles both branches.

- paid:   payments=paid, consultations=confirmed, slots=booked (+outbox payment.captured)
- failed: payments=failed, consultations=cancelled, slots=open (compensation)
Webhook is idempotent: repeated delivery with the same gateway_ref returns the
stored payment without re-applying side effects (INSERT … ON CONFLICT + status guard).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.api.deps import AuthUser
from amrutam.core.audit import write_audit
from amrutam.core.errors import BadRequest, Conflict, Forbidden, NotFound
from amrutam.core.observability import payments_total
from amrutam.modules.payments import gateway


async def create_intent(
    db: AsyncSession,
    redis: Any,
    user: AuthUser,
    consultation_id: str,
    amount: int,
    currency: str,
    force_fail: bool,
    idempotency_key: str,
) -> dict[str, Any]:
    if user.role not in ("patient", "admin"):
        raise Forbidden("only the patient may pay")
    async with db.begin():
        cons = (
            await db.execute(
                text("SELECT id::text, patient_id::text, status FROM consultations WHERE id = :c"),
                {"c": consultation_id},
            )
        ).first()
        if cons is None:
            raise NotFound("consultation not found")
        if user.role == "patient" and cons[1] != user.id:
            raise Forbidden("not your consultation")
        if cons[2] not in ("held",):
            raise BadRequest(f"cannot pay in status {cons[2]}")
        # Idempotent intent: same consultation returns existing row (unique).
        existing = (
            await db.execute(
                text(
                    "SELECT id::text, consultation_id::text, status, gateway_ref "
                    "FROM payments WHERE consultation_id = :c"
                ),
                {"c": consultation_id},
            )
        ).first()
        if existing is not None:
            return {
                "id": existing[0],
                "consultation_id": existing[1],
                "status": existing[2],
                "gateway_ref": existing[3],
            }
        result = await gateway.charge(consultation_id, amount, idempotency_key, force_fail)
        pay = (
            await db.execute(
                text(
                    "INSERT INTO payments (consultation_id, amount, currency, status, gateway_ref) "
                    "VALUES (:c, :a, :cur, 'pending', :g) RETURNING id::text"
                ),
                {"c": consultation_id, "a": amount, "cur": currency, "g": result["gateway_ref"]},
            )
        ).scalar_one()
        await db.execute(
            text(
                "INSERT INTO outbox_events (aggregate, event, payload) "
                "VALUES ('payment', 'payment.initiated', :pl)"
            ),
            {"pl": json.dumps({"consultation_id": consultation_id, "payment_id": pay})},
        )
    # Synchronous mock settlement (prod: async webhook from gateway).
    # Reuse the webhook path so both entry points share settlement logic.
    return await apply_webhook(
        db,
        consultation_id,
        "failed" if result["ok"] is False else "paid",
        str(result["gateway_ref"]),
    )


async def apply_webhook(
    db: AsyncSession, consultation_id: str, status: str, gateway_ref: str
) -> dict[str, Any]:
    if status not in ("paid", "failed"):
        raise BadRequest("status must be paid|failed")
    async with db.begin():
        pay = (
            await db.execute(
                text(
                    "SELECT id::text, consultation_id::text, status, gateway_ref "
                    "FROM payments WHERE consultation_id = :c"
                ),
                {"c": consultation_id},
            )
        ).first()
        if pay is None:
            raise NotFound("payment intent not found")
        # Idempotent replay: same terminal state + same ref → return stored row.
        if pay[2] in ("paid", "failed") and pay[3] == gateway_ref:
            return {
                "id": pay[0],
                "consultation_id": pay[1],
                "status": pay[2],
                "gateway_ref": pay[3],
            }
        if pay[2] in ("paid", "failed"):
            raise Conflict("payment already settled differently", code="payment_settled")

        cons = (
            await db.execute(
                text("SELECT id::text, slot_id::text, status FROM consultations WHERE id = :c"),
                {"c": consultation_id},
            )
        ).first()
        if cons is None:
            raise NotFound("consultation not found")
        slot_id = cons[1]

        if status == "paid":
            await db.execute(
                text("UPDATE payments SET status = 'paid', gateway_ref = :g WHERE id = :p"),
                {"g": gateway_ref, "p": pay[0]},
            )
            await db.execute(
                text("UPDATE consultations SET status = 'confirmed' WHERE id = :c"),
                {"c": consultation_id},
            )
            await db.execute(
                text(
                    "UPDATE availability_slots SET status = 'booked' "
                    "WHERE id = :s AND status = 'held'"
                ),
                {"s": slot_id},
            )
            await db.execute(
                text(
                    "INSERT INTO outbox_events (aggregate, event, payload) "
                    "VALUES ('payment', 'payment.captured', :pl)"
                ),
                {"pl": json.dumps({"consultation_id": consultation_id})},
            )
        else:
            await db.execute(
                text("UPDATE payments SET status = 'failed', gateway_ref = :g WHERE id = :p"),
                {"g": gateway_ref, "p": pay[0]},
            )
            # compensation: cancel consultation + release slot (re-runnable)
            await db.execute(
                text("UPDATE consultations SET status = 'cancelled' WHERE id = :c"),
                {"c": consultation_id},
            )
            await db.execute(
                text(
                    "UPDATE availability_slots SET status = 'open' "
                    "WHERE id = :s AND status IN ('held', 'booked')"
                ),
                {"s": slot_id},
            )
            await write_audit(
                db,
                actor="system",
                action="payment.failed.compensate",
                entity="consultation",
                entity_id=consultation_id,
                payload={"gateway_ref": gateway_ref},
            )
            await db.execute(
                text(
                    "INSERT INTO outbox_events (aggregate, event, payload) "
                    "VALUES ('payment', 'payment.failed', :pl)"
                ),
                {"pl": json.dumps({"consultation_id": consultation_id})},
            )
    row = (
        await db.execute(
            text(
                "SELECT id::text, consultation_id::text, status, gateway_ref "
                "FROM payments WHERE consultation_id = :c"
            ),
            {"c": consultation_id},
        )
    ).first()
    await db.rollback()
    assert row is not None
    payments_total.labels(status=str(row[2])).inc()
    return {"id": row[0], "consultation_id": row[1], "status": row[2], "gateway_ref": row[3]}
