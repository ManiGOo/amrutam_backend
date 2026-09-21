"""Admin analytics over materialized views (refreshed by scheduler cron)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def refresh_matviews(db: AsyncSession) -> None:
    async with db.begin():
        await db.execute(text("REFRESH MATERIALIZED VIEW analytics_daily;"))
        await db.execute(text("REFRESH MATERIALIZED VIEW analytics_funnel;"))


async def daily(db: AsyncSession, limit: int = 30) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            text("SELECT day::text, status, n FROM analytics_daily ORDER BY day DESC LIMIT :l"),
            {"l": limit},
        )
    ).all()
    await db.rollback()
    return [{"day": r[0], "status": r[1], "n": r[2]} for r in rows]


async def funnel(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(text("SELECT status, n FROM analytics_funnel ORDER BY n DESC"))).all()
    await db.rollback()
    return [{"status": r[0], "n": r[1]} for r in rows]
