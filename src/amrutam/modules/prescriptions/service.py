"""Prescription use cases: sealed PHI at rest, PDF in object store, signed-URL read."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.api.deps import AuthUser
from amrutam.core.audit import write_audit
from amrutam.core.config import Settings
from amrutam.core.errors import BadRequest, Forbidden, NotFound
from amrutam.modules.prescriptions import crypto
from amrutam.modules.prescriptions.pdf_store import PdfStore, render_rx_pdf

PRESCRIBABLE = ("confirmed", "in_progress", "completed")


async def _consultation(db: AsyncSession, cid: str) -> Any:
    row = (
        await db.execute(
            text(
                "SELECT id::text, patient_id::text, doctor_id::text, status "
                "FROM consultations WHERE id = :c"
            ),
            {"c": cid},
        )
    ).first()
    if row is None:
        raise NotFound("consultation not found")
    return row


def _can_read(cons: Any, user: AuthUser) -> None:
    if user.role == "admin":
        return
    if user.role == "patient" and cons[1] == user.id:
        return
    if user.role == "doctor" and cons[2] == user.id:
        return
    raise Forbidden("not your prescription")


async def create_prescription(
    db: AsyncSession,
    store: PdfStore,
    settings: Settings,
    consultation_id: str,
    user: AuthUser,
    diagnosis: str,
    medicines: list[str],
) -> dict[str, str]:
    if user.role not in ("doctor", "admin"):
        raise Forbidden("only the treating doctor may prescribe")
    async with db.begin():
        cons = await _consultation(db, consultation_id)
        if user.role == "doctor" and cons[2] != user.id:
            raise Forbidden("not your consultation")
        if cons[3] not in PRESCRIBABLE:
            raise BadRequest(f"cannot prescribe in status {cons[3]}")
        payload = json.dumps(
            {
                "diagnosis": diagnosis,
                "medicines": medicines,
                "consultation_id": consultation_id,
                "doctor_id": user.id,
                "issued_at": datetime.now(UTC).isoformat(),
            }
        ).encode()
        wrapped_dek, nonce, ct = crypto.seal(payload, settings.prescription_kek_b64)
        rx_id: str = (
            await db.execute(
                text(
                    "INSERT INTO prescriptions (consultation_id, encrypted_payload, "
                    "wrapped_dek, nonce) VALUES (:c, :ct, :w, :n) RETURNING id::text"
                ),
                {"c": consultation_id, "ct": ct, "w": wrapped_dek, "n": nonce},
            )
        ).scalar_one()
        pdf = render_rx_pdf(consultation_id, user.id, diagnosis, medicines)
        key = f"rx/{rx_id}.pdf"
        await store.put(key, pdf)
        await write_audit(
            db,
            actor=user.id,
            action="prescription.issued",
            entity="prescription",
            entity_id=rx_id,
            payload={"consultation_id": consultation_id},
        )
        await db.execute(
            text(
                "INSERT INTO outbox_events (aggregate, event, payload) "
                "VALUES ('prescription', 'prescription.issued', :pl)"
            ),
            {"pl": json.dumps({"prescription_id": rx_id, "consultation_id": consultation_id})},
        )
    return {"id": rx_id, "consultation_id": consultation_id}


async def view_prescription(
    db: AsyncSession, settings: Settings, rx_id: str, user: AuthUser
) -> dict[str, Any]:
    row = (
        await db.execute(
            text(
                "SELECT id::text, consultation_id::text, encrypted_payload, "
                "wrapped_dek, nonce FROM prescriptions "
                "WHERE id = :r AND deleted_at IS NULL"
            ),
            {"r": rx_id},
        )
    ).first()
    if row is None:
        raise NotFound("prescription not found")
    cons = await _consultation(db, row[1])
    _can_read(cons, user)
    await db.rollback()  # close autobegun read tx
    if row[3] is None or row[4] is None:
        raise BadRequest("legacy prescription without envelope — reissue required")
    raw = crypto.open_envelope(
        bytes(row[3]), bytes(row[4]), bytes(row[2]), settings.prescription_kek_b64
    )
    data = json.loads(raw)
    return {
        "id": row[0],
        "consultation_id": row[1],
        "diagnosis": data["diagnosis"],
        "medicines": data["medicines"],
    }


async def pdf_signed_url(
    db: AsyncSession, store: PdfStore, rx_id: str, user: AuthUser, ttl_s: int = 300
) -> dict[str, Any]:
    row = (
        await db.execute(
            text("SELECT id::text, consultation_id::text FROM prescriptions WHERE id = :r"),
            {"r": rx_id},
        )
    ).first()
    if row is None:
        raise NotFound("prescription not found")
    cons = await _consultation(db, row[1])
    _can_read(cons, user)
    await db.rollback()
    url = await store.signed_url(f"rx/{rx_id}.pdf", ttl_s)
    return {"url": url, "expires_in_s": ttl_s}
