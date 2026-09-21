"""Booking use case: idempotent, concurrent-safe, single-tx + outbox.

Flow (mirrors build.md §4 sequence diagram):
  Redis replay check → BEGIN → idempotency_keys INSERT … ON CONFLICT DO NOTHING
  → advisory xact lock → SELECT slot FOR UPDATE SKIP LOCKED
  → UPDATE slots (optimistic version) → INSERT consultations(held)
  → INSERT audit_logs → INSERT outbox_events → COMMIT
  → mark idempotency completed → Redis replay save → XADD stream (best-effort)
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.core import idempotency as idem
from amrutam.core.audit import write_audit
from amrutam.core.errors import Conflict, NotFound
from amrutam.core.observability import bookings_total, idempotency_replays_total


async def _pg_replay(db: AsyncSession, key: str) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(
                "SELECT status, response_code, response_body FROM idempotency_keys "
                "WHERE key = :k"
            ),
            {"k": key},
        )
    ).first()
    if row and row[0] == "completed" and row[2] is not None:
        body = row[2]
        if isinstance(body, str):
            body = json.loads(body)
        return {"status": row[1] or 202, "body": body}
    return None


async def handle_booking(
    db: AsyncSession,
    redis: Any,
    patient_id: str,
    slot_id: str,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    # 1. Fast path: Redis replay (verbatim response).
    cached = await idem.get_replay(redis, idempotency_key)
    if cached is not None:
        idempotency_replays_total.inc()
        return cached["body"], True

    # 2. Durable fallback: PG completed row (covers Redis eviction/restart).
    # Plain SELECT autobegins a tx; roll back to keep the session clean for step 3.
    existing = await _pg_replay(db, idempotency_key)
    await db.rollback()
    if existing is not None:
        await idem.save_replay(redis, idempotency_key, existing["status"], existing["body"])
        idempotency_replays_total.inc()
        return existing["body"], True

    # 3. Main transaction (single unit of work).
    async with db.begin():
        ins = (
            await db.execute(
                text(
                    "INSERT INTO idempotency_keys (key, status) VALUES (:k, 'pending') "
                    "ON CONFLICT (key) DO NOTHING RETURNING key"
                ),
                {"k": idempotency_key},
            )
        ).first()
        if ins is None:
            # Same key seen before: either concurrent processing or completed
            # after the step-2 check raced us. Re-read inside tx.
            prior = await _pg_replay(db, idempotency_key)
            if prior is not None:
                await idem.save_replay(redis, idempotency_key, prior["status"], prior["body"])
                idempotency_replays_total.inc()
                return prior["body"], True
            raise Conflict("concurrent request with same idempotency key", code="conflict")

        locked = await idem.acquire_advisory_lock(db, idempotency_key)
        if not locked:
            raise Conflict("concurrent request with same idempotency key", code="conflict")

        slot = (
            await db.execute(
                text(
                    "SELECT id::text, doctor_id::text, version, status "
                    "FROM availability_slots WHERE id = :s FOR UPDATE SKIP LOCKED"
                ),
                {"s": slot_id},
            )
        ).first()
        if slot is None:
            # Distinguish locked-vs-missing for a precise error.
            exists = (
                await db.execute(
                    text("SELECT 1 FROM availability_slots WHERE id = :s"), {"s": slot_id}
                )
            ).first()
            if exists is None:
                raise NotFound("slot not found")
            raise Conflict("slot is locked or already taken", code="slot_taken")

        slot_id_txt, doctor_id_txt, version, status = slot[0], slot[1], slot[2], slot[3]
        if status != "open":
            raise Conflict(f"slot not open (status={status})", code="slot_taken")

        upd = await db.execute(
            text(
                "UPDATE availability_slots SET status = 'held', version = version + 1 "
                "WHERE id = :s AND version = :v AND status = 'open'"
            ),
            {"s": slot_id, "v": version},
        )
        if getattr(upd, "rowcount", 0) != 1:
            raise Conflict("slot taken by concurrent booking", code="slot_taken")

        cons = (
            await db.execute(
                text(
                    "INSERT INTO consultations (patient_id, doctor_id, slot_id, status) "
                    "VALUES (:p, :d, :s, 'held') RETURNING id::text"
                ),
                {"p": patient_id, "d": doctor_id_txt, "s": slot_id_txt},
            )
        ).one()
        consultation_id: str = cons[0]

        await write_audit(
            db,
            actor=patient_id,
            action="book_slot",
            entity="consultation",
            entity_id=consultation_id,
            payload={"slot_id": slot_id_txt, "doctor_id": doctor_id_txt},
        )
        await db.execute(
            text(
                "INSERT INTO outbox_events (aggregate, event, payload) "
                "VALUES ('consultation', 'booking.created', :pl)"
            ),
            {
                "pl": json.dumps(
                    {
                        "consultation_id": consultation_id,
                        "slot_id": slot_id_txt,
                        "patient_id": patient_id,
                        "doctor_id": doctor_id_txt,
                    }
                ),
            },
        )
    # tx committed here.

    body = {"id": consultation_id, "status": "held", "slot_id": slot_id_txt}

    # 4. Mark idempotent (durable) + cache replay. Separate tx so booking stays
    # committed even if bookkeeping fails; failures here only cost a slower retry path.
    async with db.begin():
        await db.execute(
            text(
                "UPDATE idempotency_keys SET status = 'completed', response_code = 202, "
                "response_body = :b WHERE key = :k"
            ),
            {"b": json.dumps(body), "k": idempotency_key},
        )
    await idem.save_replay(redis, idempotency_key, 202, body)

    # 5. Best-effort stream fan-out (relay worker is source of truth via outbox poll).
    try:
        await redis.xadd(
            "streams:events",
            {"event": "booking.created", "consultation_id": consultation_id},
        )
    except Exception as e:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).debug("best-effort xadd failed: %s", e)
    bookings_total.labels(status="held").inc()
    return body, False
