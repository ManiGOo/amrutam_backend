"""Append-only chain-hash audit writer shared by services + middleware.

hash = sha256(prev_hash || actor || action || entity:entity_id || payload)
Serialized per-tx with an advisory lock so concurrent writers can't fork the chain.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def write_audit(
    db: AsyncSession,
    actor: str,
    action: str,
    entity: str,
    entity_id: str,
    payload: str | dict[str, Any],
) -> str:
    if isinstance(payload, dict):
        payload = json.dumps(payload)
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('audit_chain'))"))
    prev = (
        await db.execute(text("SELECT hash FROM audit_logs ORDER BY ts DESC, id DESC LIMIT 1"))
    ).first()
    prev_hash = prev[0] if prev and prev[0] else ""
    digest = hashlib.sha256(
        f"{prev_hash}|{actor}|{action}|{entity}:{entity_id}|{payload}".encode()
    ).hexdigest()
    await db.execute(
        text(
            "INSERT INTO audit_logs (actor, action, entity, entity_id, payload, "
            "prev_hash, hash) VALUES (:a, :act, :e, :eid, :pl, :ph, :h)"
        ),
        {
            "a": actor,
            "act": action,
            "e": entity,
            "eid": entity_id,
            "pl": payload,
            "ph": prev_hash,
            "h": digest,
        },
    )
    return digest
