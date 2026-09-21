"""Idempotency replay cache (Redis) + Postgres advisory-lock helper.

Redis is a *cache* here, never the authority: every helper degrades to a miss
on connection errors so bookings stay correct (via the PG idempotency_keys
fallback) during a Redis outage. The durable PG row is the source of truth.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

TTL_SECONDS = 24 * 3600


def cache_key(key: str) -> str:
    return f"idem:{key}"


async def get_replay(redis: Any, key: str) -> dict[str, Any] | None:
    try:
        raw = await redis.get(cache_key(key))
    except Exception as e:  # noqa: BLE001 — Redis down → durable PG fallback
        log.warning("idem replay miss (redis down): %s", e)
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, TypeError):
        return None


async def save_replay(redis: Any, key: str, status: int, body: dict[str, Any]) -> None:
    try:
        await redis.set(
            cache_key(key), json.dumps({"status": status, "body": body}), ex=TTL_SECONDS
        )
    except Exception as e:  # noqa: BLE001 — PG row already durable; cache refills later
        log.warning("idem replay save skipped (redis down): %s", e)


async def acquire_advisory_lock(db: AsyncSession, key: str) -> bool:
    """pg_try_advisory_xact_lock — auto-released at tx end. Must run inside tx."""
    row = (
        await db.execute(text("SELECT pg_try_advisory_xact_lock(hashtext(:k))"), {"k": key})
    ).first()
    return bool(row and row[0])
