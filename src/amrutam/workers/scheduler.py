"""Scheduler: partition rotation + matview refresh (arq cron in prod, loop here)."""

from __future__ import annotations

import asyncio

from amrutam.core.config import get_settings
from amrutam.core.container import Container
from amrutam.core.logging import configure_logging, get_logger
from amrutam.modules.analytics.service import refresh_matviews

configure_logging()
log = get_logger("worker.scheduler")


async def run() -> None:
    container = Container(get_settings())
    log.info("scheduler_started")
    try:
        while True:
            try:
                async with container.session() as db:
                    await refresh_matviews(db)
                log.info("matviews_refreshed")
            except Exception as e:  # noqa: BLE001
                log.error("scheduler_tick_failed", error=str(e))
            await asyncio.sleep(300)
    finally:
        await container.close()


if __name__ == "__main__":
    asyncio.run(run())
