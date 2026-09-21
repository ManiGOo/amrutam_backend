"""Outbox relay: PG outbox_events → Redis Streams (at-least-once, idempotent consumers).

Polls `outbox_events WHERE processed=false FOR UPDATE SKIP LOCKED LIMIT 100`,
XADDs each event to `streams:events`, marks processed. Relay is the source of
truth — the booking endpoint's inline XADD is best-effort only.
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from amrutam.core.config import get_settings
from amrutam.core.container import Container
from amrutam.core.logging import configure_logging, get_logger
from amrutam.core.observability import outbox_relayed_total

configure_logging()
log = get_logger("worker.relay")

BATCH = 100
POLL_S = 1.0


async def relay_once(container: Container) -> int:
    async with container.session() as db:
        async with db.begin():
            rows = (
                await db.execute(
                    text(
                        "SELECT id::text, event, payload::text FROM outbox_events "
                        "WHERE processed = FALSE ORDER BY created_at "
                        "FOR UPDATE SKIP LOCKED LIMIT :l"
                    ),
                    {"l": BATCH},
                )
            ).all()
            if not rows:
                return 0
            redis = await container.get_redis()
            for event_id, event, payload in rows:
                try:
                    fields = {"event": event, "payload": payload}
                    try:
                        data = json.loads(payload)
                        if isinstance(data, dict) and "consultation_id" in data:
                            fields["consultation_id"] = str(data["consultation_id"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                    await redis.xadd("streams:events", fields)
                except Exception as e:  # noqa: BLE001
                    log.error("relay_xadd_failed", event_id=event_id, error=str(e))
                    continue
                await db.execute(
                    text(
                        "UPDATE outbox_events SET processed = TRUE, processed_at = now() "
                        "WHERE id = :i"
                    ),
                    {"i": event_id},
                )
                log.info("relayed", event_id=event_id, evt=event)
                try:
                    outbox_relayed_total.labels(event=event).inc()
                except Exception as e:  # noqa: BLE001
                    log.debug("metric inc skipped", error=str(e))
            return len(rows)


async def run() -> None:
    container = Container(get_settings())
    log.info("relay_started")
    try:
        while True:
            try:
                n = await relay_once(container)
            except Exception as e:  # noqa: BLE001
                log.error("relay_batch_failed", error=str(e))
                n = 0
            await asyncio.sleep(0 if n >= BATCH else POLL_S)
    finally:
        await container.close()


if __name__ == "__main__":
    asyncio.run(run())
